package service

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	wireprotocol "github.com/ybz21/Roami/internal/modelgateway/protocol"
	"github.com/ybz21/Roami/internal/modelgateway/protocoltest"
)

func assertUpstreamContract(t *testing.T, raw map[string]any, format string) {
	t.Helper()
	if raw["model"] != "fixture" {
		t.Errorf("upstream received an internal model alias: %v", raw["model"])
	}
	s, _ := json.Marshal(raw)
	for _, expected := range []string{"policy", "call_prior", "prior-result", "next", "before", "write_file"} {
		if !strings.Contains(string(s), expected) {
			t.Errorf("request lost %s: %s", expected, s)
		}
	}
	switch format {
	case "openai-completions":
		if raw["input"] != nil || raw["system"] != nil {
			t.Error("native fields escaped into Chat Completions")
		}
		m := arrayValue(raw["messages"])
		if len(m) < 4 || fieldText(objectValue(m[0]), "role") != "system" {
			t.Error("system instruction was not preserved")
		}
		tool := objectValue(arrayValue(raw["tools"])[0])
		if fieldText(tool, "type") != "function" || objectValue(tool["function"])["parameters"] == nil {
			t.Error("Chat tool schema is missing")
		}
	case "anthropic-messages":
		if raw["input"] != nil || raw["instructions"] != nil {
			t.Error("native fields escaped into Messages")
		}
		if raw["system"] == nil || raw["max_tokens"] == nil {
			t.Error("Messages requires system and output bounds")
		}
		tool := objectValue(arrayValue(raw["tools"])[0])
		if tool["input_schema"] == nil {
			t.Error("Messages tool schema is missing")
		}
	case "openai-responses":
		if raw["messages"] != nil || raw["system"] != nil || raw["store"] != false {
			t.Error("Responses payload shape or stateless mode is wrong")
		}
		if raw["input"] == nil {
			t.Error("Responses input is missing")
		}
		tool := objectValue(arrayValue(raw["tools"])[0])
		if tool["parameters"] == nil || tool["function"] != nil {
			t.Error("Responses tool schema is not flat")
		}
	}
}
func TestGatewayConvertsAllProtocolPairsWithoutDuplicatingSources(t *testing.T) {
	protocols := []string{"openai-completions", "anthropic-messages", "openai-responses"}
	for _, source := range protocols {
		for _, target := range protocols {
			if source == target {
				continue
			}
			for _, stream := range []bool{false, true} {
				t.Run(fmt.Sprintf("%s_to_%s_stream_%v", source, target, stream), func(t *testing.T) {
					upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
						paths := map[string]string{"openai-completions": "/v1/chat/completions", "anthropic-messages": "/v1/messages", "openai-responses": "/v1/responses"}
						if r.URL.Path != paths[source] || r.Header.Get("Authorization") != "Bearer upstream-secret" || r.Header.Get("Cookie") != "" || r.Header.Get("X-Roami-Owner") != "" {
							t.Error("route or credential boundary changed")
						}
						var raw map[string]any
						_ = json.NewDecoder(r.Body).Decode(&raw)
						assertUpstreamContract(t, raw, source)
						protocoltest.WriteResponse(w, source, stream)
					}))
					defer upstream.Close()
					h := catalogHandler(t, upstream.URL+"/v1", source)
					body, _ := json.Marshal(protocoltest.Request(target, stream))
					paths := map[string]string{"openai-completions": "/v1/chat/completions", "anthropic-messages": "/v1/messages", "openai-responses": "/v1/responses"}
					w := httptest.NewRecorder()
					r := httptest.NewRequest("POST", paths[target], strings.NewReader(string(body)))
					r.Header.Set("Authorization", "Bearer "+h.Catalog.credential("opencode"))
					r.Header.Set("Cookie", "caller-private-cookie")
					r.Header.Set("X-Roami-Owner", "private-owner")
					h.publicModels(w, r)
					if w.Code != 200 || strings.Contains(w.Body.String(), "upstream-secret") {
						t.Fatalf("forward failed: %d %s", w.Code, w.Body)
					}
					var result *wireprotocol.Result
					var err error
					if stream {
						result = wireprotocol.NewResult()
						for _, line := range strings.Split(w.Body.String(), "\n") {
							if strings.HasPrefix(line, "data:") {
								if err = result.Consume([]byte(strings.TrimSpace(line[5:])), target, func(string) error { return nil }); err != nil {
									t.Fatalf("invalid downstream event: %v %s", err, w.Body)
								}
							}
						}
						if !result.Terminal {
							t.Fatalf("missing terminal event: %s", w.Body)
						}
						sequence := -1
						if target == "openai-responses" {
							for _, line := range strings.Split(w.Body.String(), "\n") {
								if strings.HasPrefix(line, "data:") {
									var event map[string]any
									_ = json.Unmarshal([]byte(strings.TrimSpace(line[5:])), &event)
									n, ok := event["sequence_number"].(float64)
									if !ok || int(n) <= sequence {
										t.Error("missing or unordered Responses sequence")
									}
									sequence = int(n)
								}
							}
						}
					} else {
						var raw map[string]any
						_ = json.Unmarshal(w.Body.Bytes(), &raw)
						result, err = wireprotocol.DecodeResult(raw, target)
					}
					if err != nil || result == nil || result.Text != "Ready" || len(result.Calls) != 1 {
						t.Fatalf("response lost content: %v %s", err, w.Body)
					}
					call := result.CallsInOrder()[0]
					if call.ID != "call_write" || call.Name != "write_file" || call.Arguments != "{\"path\":\"out.txt\"}" {
						t.Fatalf("tool call changed: %+v", call)
					}
					var input, output, cached int64
					if err = h.state.db.QueryRow("SELECT input_tokens,output_tokens,cache_read_tokens FROM gateway_calls LIMIT 1").Scan(&input, &output, &cached); err != nil {
						t.Fatal(err)
					}
					if input != 100 || output != 7 || cached != 20 {
						t.Fatalf("usage was not settled in the upstream format: %d %d %d", input, output, cached)
					}
				})
			}
		}
	}
}
func TestSharedSourceAppliesNativeProtocolsAndListsModelsForEveryAgent(t *testing.T) {
	for _, kind := range []string{"claude", "codex", "opencode", "pi"} {
		t.Run(kind, func(t *testing.T) {
			h := catalogHandler(t, "https://shared.example/v1", "openai-completions")
			view, err := h.Catalog.agents.View(context.Background(), kind)
			if err != nil {
				t.Fatal(err)
			}
			input := map[string]any{"kind": kind, "sourceId": "work", "model": "coding-main", "revision": view.Revision, "catalogRevision": h.Catalog.value.Revision}
			body, _ := json.Marshal(input)
			w := httptest.NewRecorder()
			h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(body))))
			if w.Code != 200 {
				t.Fatalf("apply: %d %s", w.Code, w.Body)
			}
			view, err = h.Catalog.agents.View(context.Background(), kind)
			if err != nil {
				t.Fatal(err)
			}
			if len(view.Profiles) != 1 || !view.Profiles[0].Applied || view.Profiles[0].Protocol != nativeProtocol(kind) {
				t.Fatalf("wrong native connection: %+v", view.Profiles)
			}
			w = httptest.NewRecorder()
			r := httptest.NewRequest("GET", "/v1/models", nil)
			r.Header.Set("Authorization", "Bearer "+h.Catalog.credential(kind))
			h.publicModels(w, r)
			if w.Code != 200 || !strings.Contains(w.Body.String(), "work/fixture") {
				t.Fatal("shared model hidden from agent")
			}
		})
	}
}
func TestGatewayRejectsUnsupportedContentBeforeAdmissionAndReportsBrokenStreams(t *testing.T) {
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"partial\"}}]}\n\n")
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL+"/v1", "openai-completions")
	request := func(value map[string]any) *httptest.ResponseRecorder {
		body, _ := json.Marshal(value)
		r := httptest.NewRequest("POST", "/v1/messages", strings.NewReader(string(body)))
		r.Header.Set("Authorization", "Bearer "+h.Catalog.credential("claude"))
		w := httptest.NewRecorder()
		h.publicModels(w, r)
		return w
	}
	input := protocoltest.Request("anthropic-messages", true)
	input["tools"] = []any{map[string]any{"type": "web_search_20250305", "name": "web_search"}}
	if w := request(input); w.Code != 400 || hits.Load() != 0 {
		t.Fatal("unsupported provider tools were sent upstream")
	}
	var count int
	if err := h.state.db.QueryRow("SELECT count(*) FROM gateway_calls").Scan(&count); err != nil || count != 0 {
		t.Fatal("invalid content was admitted or billed")
	}
	w := request(protocoltest.Request("anthropic-messages", true))
	if hits.Load() != 1 || !strings.Contains(w.Body.String(), "MODEL_GATEWAY_INTERRUPTED") || strings.Contains(w.Body.String(), "message_stop") {
		t.Fatalf("truncated stream looked successful: %s", w.Body)
	}
}

func TestGatewayStreamsTextBeforeUpstreamCompletion(t *testing.T) {
	release := make(chan struct{})
	arrived := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "data: {\"choices\":[{\"index\":0,\"delta\":{\"content\":\"live text\"}}]}\n\n")
		w.(http.Flusher).Flush()
		close(arrived)
		select {
		case <-release:
		case <-r.Context().Done():
			return
		}
		_, _ = io.WriteString(w, "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":1}}\n\ndata: [DONE]\n\n")
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL+"/v1", "openai-completions")
	gateway := httptest.NewServer(http.HandlerFunc(h.publicModels))
	defer gateway.Close()
	req, _ := http.NewRequest("POST", gateway.URL+"/v1/messages", strings.NewReader("{\"model\":\"coding-main\",\"stream\":true,\"max_tokens\":16,\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}"))
	req.Header.Set("Authorization", "Bearer "+h.Catalog.credential("claude"))
	response, err := (&http.Client{Timeout: 3 * time.Second}).Do(req)
	if err != nil {
		close(release)
		t.Fatal(err)
	}
	defer response.Body.Close()
	reader := bufio.NewReader(response.Body)
	seen := false
	for i := 0; i < 12; i++ {
		line, e := reader.ReadString('\n')
		if e != nil {
			break
		}
		if strings.Contains(line, "live text") {
			seen = true
			break
		}
	}
	close(release)
	if !seen {
		t.Fatal("streamed text was buffered until the source finished")
	}
	<-arrived
	_, _ = io.Copy(io.Discard, reader)
}

func TestGatewayFailoverCanAdaptDifferentUpstreamFormats(t *testing.T) {
	primary := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	primary.Close()
	backup := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if r.URL.Path != "/v1/messages" || body["model"] != "backup-model" || r.Header.Get("Authorization") != "Bearer backup-secret" || r.Header.Get("Anthropic-Version") == "" {
			t.Error("fallback used the primary format or credentials")
		}
		protocoltest.WriteResponse(w, "anthropic-messages", true)
	}))
	defer backup.Close()
	h := catalogHandler(t, primary.URL+"/v1", "openai-completions")
	next := h.Catalog.snapshot()
	next.Sources = append(next.Sources, ModelSource{ID: "backup", Name: "Backup", BaseURL: backup.URL + "/v1", Protocol: "anthropic-messages", AuthMode: "bearer", APIKey: "backup-secret"})
	next.Models[0].Strategy = "failover"
	next.Models[0].Candidates = append(next.Models[0].Candidates, ModelCandidate{SourceID: "backup", Model: "backup-model"})
	if err := h.Catalog.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(protocoltest.Request("openai-responses", true))
	w := catalogRequest(h, "/v1/responses", string(body))
	if w.Code != 200 || !strings.Contains(w.Body.String(), "response.completed") {
		t.Fatalf("mixed-source fallback: %d %s", w.Code, w.Body)
	}
	var count int
	var model string
	if err := h.state.db.QueryRow("SELECT count(*) FROM gateway_calls").Scan(&count); err != nil || count != 2 {
		t.Fatal("failover attempts were not settled independently")
	}
	if err := h.state.db.QueryRow("SELECT model FROM gateway_calls WHERE http_status=200").Scan(&model); err != nil || model != "backup-model" {
		t.Fatal("fallback charged the wrong model")
	}
}

func objectValue(v any) map[string]any              { value, _ := v.(map[string]any); return value }
func arrayValue(v any) []any                        { value, _ := v.([]any); return value }
func fieldText(v map[string]any, key string) string { value, _ := v[key].(string); return value }
