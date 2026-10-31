package modelgateway

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
)

func protocolFixtureRequest(format string, stream bool) map[string]any {
	schema := map[string]any{"type": "object", "properties": map[string]any{"path": map[string]any{"type": "string"}}, "required": []string{"path"}}
	out := map[string]any{"model": "coding-main", "stream": stream}
	switch format {
	case "openai-completions":
		out["messages"] = []any{map[string]any{"role": "system", "content": "policy"}, map[string]any{"role": "assistant", "content": nil, "tool_calls": []any{map[string]any{"id": "call_prior", "type": "function", "function": map[string]any{"name": "write_file", "arguments": "{\"path\":\"before\"}"}}}}, map[string]any{"role": "tool", "tool_call_id": "call_prior", "content": "prior-result"}, map[string]any{"role": "user", "content": "next"}}
		out["tools"] = []any{map[string]any{"type": "function", "function": map[string]any{"name": "write_file", "parameters": schema}}}
	case "anthropic-messages":
		out["system"] = "policy"
		out["max_tokens"] = 128
		out["messages"] = []any{map[string]any{"role": "assistant", "content": []any{map[string]any{"type": "tool_use", "id": "call_prior", "name": "write_file", "input": map[string]any{"path": "before"}}}}, map[string]any{"role": "user", "content": []any{map[string]any{"type": "tool_result", "tool_use_id": "call_prior", "content": "prior-result"}, map[string]any{"type": "text", "text": "next"}}}}
		out["tools"] = []any{map[string]any{"name": "write_file", "input_schema": schema}}
	case "openai-responses":
		out["instructions"] = "policy"
		out["input"] = []any{map[string]any{"type": "function_call", "call_id": "call_prior", "name": "write_file", "arguments": "{\"path\":\"before\"}"}, map[string]any{"type": "function_call_output", "call_id": "call_prior", "output": "prior-result"}, map[string]any{"type": "message", "role": "user", "content": []any{map[string]any{"type": "input_text", "text": "next"}}}}
		out["tools"] = []any{map[string]any{"type": "function", "name": "write_file", "parameters": schema}}
	}
	return out
}
func fixtureProtocolUsage(format string) map[string]any {
	switch format {
	case "anthropic-messages":
		return map[string]any{"input_tokens": 80, "output_tokens": 7, "cache_read_input_tokens": 20}
	case "openai-responses":
		return map[string]any{"input_tokens": 100, "output_tokens": 7, "input_tokens_details": map[string]any{"cached_tokens": 20}}
	default:
		return map[string]any{"prompt_tokens": 100, "completion_tokens": 7, "prompt_tokens_details": map[string]any{"cached_tokens": 20}}
	}
}
func fixtureProtocolResponse(format string) map[string]any {
	usage := fixtureProtocolUsage(format)
	switch format {
	case "anthropic-messages":
		return map[string]any{"id": "msg_fixture", "type": "message", "role": "assistant", "model": "fixture", "content": []any{map[string]any{"type": "text", "text": "Ready"}, map[string]any{"type": "tool_use", "id": "call_write", "name": "write_file", "input": map[string]any{"path": "out.txt"}}}, "stop_reason": "tool_use", "usage": usage}
	case "openai-responses":
		return map[string]any{"id": "resp_fixture", "status": "completed", "output": []any{map[string]any{"type": "message", "role": "assistant", "content": []any{map[string]any{"type": "output_text", "text": "Ready"}}}, map[string]any{"type": "function_call", "call_id": "call_write", "name": "write_file", "arguments": "{\"path\":\"out.txt\"}"}}, "usage": usage}
	default:
		return map[string]any{"id": "chat_fixture", "choices": []any{map[string]any{"index": 0, "message": map[string]any{"role": "assistant", "content": "Ready", "tool_calls": []any{map[string]any{"type": "function", "id": "call_write", "function": map[string]any{"name": "write_file", "arguments": "{\"path\":\"out.txt\"}"}}}}, "finish_reason": "tool_calls"}}, "usage": usage}
	}
}
func writeProtocolFixture(w http.ResponseWriter, format string, stream bool) {
	if !stream {
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(fixtureProtocolResponse(format))
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	send := func(value map[string]any) {
		raw, _ := json.Marshal(value)
		if kind := fieldText(value, "type"); kind != "" {
			_, _ = fmt.Fprintf(w, "event: %s\n", kind)
		}
		_, _ = fmt.Fprintf(w, "data: %s\n\n", raw)
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
	}
	switch format {
	case "openai-completions":
		send(map[string]any{"choices": []any{map[string]any{"index": 0, "delta": map[string]any{"content": "Ready"}}}})
		send(map[string]any{"choices": []any{map[string]any{"index": 0, "delta": map[string]any{"tool_calls": []any{map[string]any{"index": 0, "id": "call_write", "type": "function", "function": map[string]any{"name": "write_file", "arguments": "{\"path\":"}}}}}}})
		send(map[string]any{"choices": []any{map[string]any{"index": 0, "delta": map[string]any{"tool_calls": []any{map[string]any{"index": 0, "function": map[string]any{"arguments": "\"out.txt\"}"}}}}, "finish_reason": "tool_calls"}}})
		send(map[string]any{"choices": []any{}, "usage": fixtureProtocolUsage(format)})
		_, _ = io.WriteString(w, "data: [DONE]\n\n")
	case "anthropic-messages":
		send(map[string]any{"type": "message_start", "message": map[string]any{"usage": map[string]any{"input_tokens": 80, "output_tokens": 0, "cache_read_input_tokens": 20}}})
		send(map[string]any{"type": "content_block_start", "index": 0, "content_block": map[string]any{"type": "text", "text": ""}})
		send(map[string]any{"type": "content_block_delta", "index": 0, "delta": map[string]any{"type": "text_delta", "text": "Ready"}})
		send(map[string]any{"type": "content_block_stop", "index": 0})
		send(map[string]any{"type": "content_block_start", "index": 1, "content_block": map[string]any{"type": "tool_use", "id": "call_write", "name": "write_file", "input": map[string]any{}}})
		send(map[string]any{"type": "content_block_delta", "index": 1, "delta": map[string]any{"type": "input_json_delta", "partial_json": "{\"path\":\"out.txt\"}"}})
		send(map[string]any{"type": "content_block_stop", "index": 1})
		send(map[string]any{"type": "message_delta", "delta": map[string]any{"stop_reason": "tool_use"}, "usage": map[string]any{"output_tokens": 7}})
		send(map[string]any{"type": "message_stop"})
	case "openai-responses":
		send(map[string]any{"type": "response.output_text.delta", "output_index": 0, "content_index": 0, "delta": "Ready"})
		send(map[string]any{"type": "response.output_item.added", "output_index": 1, "item": map[string]any{"type": "function_call", "id": "fc_fixture", "call_id": "call_write", "name": "write_file", "arguments": ""}})
		send(map[string]any{"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "{\"path\":\"out.txt\"}"})
		send(map[string]any{"type": "response.completed", "response": fixtureProtocolResponse(format)})
	}
}
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
						writeProtocolFixture(w, source, stream)
					}))
					defer upstream.Close()
					h := catalogHandler(t, upstream.URL+"/v1", source)
					body, _ := json.Marshal(protocolFixtureRequest(target, stream))
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
					var result *protocolResult
					var err error
					if stream {
						result = newProtocolResult()
						for _, line := range strings.Split(w.Body.String(), "\n") {
							if strings.HasPrefix(line, "data:") {
								if err = result.event([]byte(strings.TrimSpace(line[5:])), target, func(string) error { return nil }); err != nil {
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
						result, err = decodeProtocolResult(raw, target)
					}
					if err != nil || result == nil || result.Text != "Ready" || len(result.Calls) != 1 {
						t.Fatalf("response lost content: %v %s", err, w.Body)
					}
					call := result.calls()[0]
					if call.ID != "call_write" || call.Name != "write_file" || call.Arguments != "{\"path\":\"out.txt\"}" {
						t.Fatalf("tool call changed: %+v", call)
					}
					var input, output, cached int64
					if err = h.Ledger.db.QueryRow("SELECT input_tokens,output_tokens,cache_read_tokens FROM gateway_calls LIMIT 1").Scan(&input, &output, &cached); err != nil {
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
			if w.Code != 200 || !strings.Contains(w.Body.String(), "coding-main") {
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
	input := protocolFixtureRequest("anthropic-messages", true)
	input["tools"] = []any{map[string]any{"type": "web_search_20250305", "name": "web_search"}}
	if w := request(input); w.Code != 400 || hits.Load() != 0 {
		t.Fatal("unsupported provider tools were sent upstream")
	}
	var count int
	if err := h.Ledger.db.QueryRow("SELECT count(*) FROM gateway_calls").Scan(&count); err != nil || count != 0 {
		t.Fatal("invalid content was admitted or billed")
	}
	w := request(protocolFixtureRequest("anthropic-messages", true))
	if hits.Load() != 1 || !strings.Contains(w.Body.String(), "MODEL_GATEWAY_INTERRUPTED") || strings.Contains(w.Body.String(), "message_stop") {
		t.Fatalf("truncated stream looked successful: %s", w.Body)
	}
}

func TestGatewayPreservesMidTurnInstructionsNamespacesAndCustomToolContracts(t *testing.T) {
	q := protocolFixtureRequest("anthropic-messages", false)
	q["messages"] = append(arrayValue(q["messages"]), map[string]any{"role": "system", "content": []any{map[string]any{"type": "text", "text": "mid-turn-policy"}}})
	body, _ := json.Marshal(q)
	converted, _, err := prepareProtocolBridge(body, "anthropic-messages", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	var value map[string]any
	_ = json.Unmarshal(converted, &value)
	messages := arrayValue(value["messages"])
	if fieldText(objectValue(messages[len(messages)-1]), "role") != "system" || !strings.Contains(string(converted), "mid-turn-policy") {
		t.Fatal("mid-turn system instruction was moved or lost")
	}
	q = protocolFixtureRequest("openai-responses", false)
	q["tools"] = []any{map[string]any{"type": "namespace", "name": "client", "description": "Client file tools", "tools": []any{map[string]any{"type": "function", "name": "write_file", "description": "Write a file", "parameters": map[string]any{"type": "object"}}}}, map[string]any{"type": "web_search", "external_web_access": true}, map[string]any{"type": "custom", "name": "apply_patch", "description": "Apply a patch", "format": map[string]any{"type": "text"}}}
	body, _ = json.Marshal(q)
	converted, bridge, err := prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	_ = json.Unmarshal(converted, &value)
	tools := arrayValue(value["tools"])
	if len(tools) != 2 || fieldText(objectValue(objectValue(tools[0])["function"]), "name") != "client__write_file" || len(bridge.request.DisabledTools) != 1 {
		t.Fatalf("namespaces or hosted-tool capability changed: %s", converted)
	}
	if !strings.Contains(string(converted), "does not provide provider-hosted tools") {
		t.Fatal("missing capability instruction")
	}
	w := httptest.NewRecorder()
	bridge.model = "coding-main"
	encoder := newProtocolEncoder(w, bridge)
	result := newProtocolResult()
	result.Calls[0] = &protocolCall{"call_namespace", "client__write_file", "{}"}
	result.Calls[1] = &protocolCall{"call_custom", "apply_patch", "{\"input\":\"patch text\"}"}
	if err = encoder.finish(result, &Usage{100, 7, 20}); err != nil {
		t.Fatal(err)
	}
	var response map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &response)
	output := arrayValue(response["output"])
	if len(output) != 2 || fieldText(objectValue(output[0]), "namespace") != "client" || fieldText(objectValue(output[0]), "name") != "write_file" || fieldText(objectValue(output[1]), "type") != "custom_tool_call" || fieldText(objectValue(output[1]), "input") != "patch text" {
		t.Fatalf("client tool identity changed: %s", w.Body)
	}
	if w.Header().Get("X-Roami-Unsupported-Tools") != "web_search" {
		t.Fatal("hosted-tool limitation was hidden")
	}
	q["tool_choice"] = map[string]any{"type": "web_search"}
	body, _ = json.Marshal(q)
	if _, _, err = prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture"); err == nil {
		t.Fatal("forced unsupported hosted search was silently downgraded")
	}
}

func TestGatewayPreservesImagesAndReasoningInToolContinuations(t *testing.T) {
	request := map[string]any{"model": "coding-main", "input": []any{
		map[string]any{"type": "message", "role": "assistant", "content": []any{map[string]any{"type": "output_text", "text": "Checking"}}},
		map[string]any{"type": "reasoning", "summary": []any{map[string]any{"type": "summary_text", "text": "portable thought"}}},
		map[string]any{"type": "function_call", "name": "write_file", "call_id": "call_1", "arguments": "{}"},
		map[string]any{"type": "function_call_output", "call_id": "call_1", "output": "written"},
		map[string]any{"role": "user", "content": []any{map[string]any{"type": "input_image", "image_url": "data:image/png;base64,ZmFrZQ=="}}},
	}}
	body, _ := json.Marshal(request)
	converted, _, err := prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	_ = json.Unmarshal(converted, &raw)
	messages := arrayValue(raw["messages"])
	assistant := objectValue(messages[0])
	if fieldText(assistant, "reasoning_content") != "portable thought" || len(arrayValue(assistant["tool_calls"])) != 1 || !strings.Contains(string(converted), "data:image/png;base64,ZmFrZQ==") {
		t.Fatalf("tool context or image lost: %s", converted)
	}
	request["input"] = []any{map[string]any{"type": "reasoning", "encrypted_content": "provider-bound"}}
	body, _ = json.Marshal(request)
	if _, _, err = prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture"); err == nil {
		t.Fatal("provider encrypted state was treated as portable text")
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
		writeProtocolFixture(w, "anthropic-messages", true)
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
	body, _ := json.Marshal(protocolFixtureRequest("openai-responses", true))
	w := catalogRequest(h, "/v1/responses", string(body))
	if w.Code != 200 || !strings.Contains(w.Body.String(), "response.completed") {
		t.Fatalf("mixed-source fallback: %d %s", w.Code, w.Body)
	}
	var count int
	var model string
	if err := h.Ledger.db.QueryRow("SELECT count(*) FROM gateway_calls").Scan(&count); err != nil || count != 2 {
		t.Fatal("failover attempts were not settled independently")
	}
	if err := h.Ledger.db.QueryRow("SELECT model FROM gateway_calls WHERE http_status=200").Scan(&model); err != nil || model != "backup-model" {
		t.Fatal("fallback charged the wrong model")
	}
}

func TestGatewayKeepsToolImagesAfterAllToolResultsAndPreservesStructuredOutputs(t *testing.T) {
	request := map[string]any{"model": "coding-main", "max_tokens": 128, "messages": []any{
		map[string]any{"role": "assistant", "content": []any{map[string]any{"type": "tool_use", "id": "image_call", "name": "read_image", "input": map[string]any{}}, map[string]any{"type": "tool_use", "id": "text_call", "name": "read_text", "input": map[string]any{}}}},
		map[string]any{"role": "user", "content": []any{map[string]any{"type": "tool_result", "tool_use_id": "image_call", "content": []any{map[string]any{"type": "image", "source": map[string]any{"type": "base64", "media_type": "image/png", "data": "ZmFrZQ=="}}}}, map[string]any{"type": "tool_result", "tool_use_id": "text_call", "content": "text-result"}}},
	}}
	body, _ := json.Marshal(request)
	converted, _, err := prepareProtocolBridge(body, "anthropic-messages", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	_ = json.Unmarshal(converted, &raw)
	messages := arrayValue(raw["messages"])
	if len(messages) != 4 || fieldText(objectValue(messages[1]), "role") != "tool" || fieldText(objectValue(messages[2]), "role") != "tool" || fieldText(objectValue(messages[3]), "role") != "user" {
		t.Fatalf("image insertion broke tool-result ordering: %s", converted)
	}
	if strings.Contains(string(mustJSON(objectValue(messages[1]))), "image_url") || !strings.Contains(string(mustJSON(objectValue(messages[3]))), "data:image/png;base64,ZmFrZQ==") {
		t.Fatal("image was lost or put in an invalid Chat tool message")
	}
	request = map[string]any{"model": "coding-main", "input": "hello", "text": map[string]any{"format": map[string]any{"type": "json_schema", "name": "answer", "schema": map[string]any{"type": "object", "properties": map[string]any{"answer": map[string]any{"type": "string"}}}, "strict": true}}}
	body, _ = json.Marshal(request)
	converted, _, err = prepareProtocolBridge(body, "openai-responses", "openai-completions", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	_ = json.Unmarshal(converted, &raw)
	spec := objectValue(objectValue(raw["response_format"])["json_schema"])
	if spec["name"] != "answer" || spec["schema"] == nil || spec["strict"] != true || spec["type"] != nil {
		t.Fatalf("structured output changed: %s", converted)
	}
}
func mustJSON(value any) []byte { raw, _ := json.Marshal(value); return raw }

func TestGatewayStreamsCCThinkingBeforeFinalText(t *testing.T) {
	for _, stream := range []bool{false, true} {
		t.Run(fmt.Sprint(stream), func(t *testing.T) {
			bridge := &protocolBridge{from: "anthropic-messages", to: "openai-completions", model: "fixture", request: protocolRequest{Stream: true}}
			body := `{"choices":[{"message":{"role":"assistant","content":"GW_NATIVE_OK","reasoning_content":"Check first"},"finish_reason":"stop"}],"usage":{"prompt_tokens":100,"completion_tokens":7}}`
			contentType := "application/json"
			if stream {
				contentType = "text/event-stream"
				body = "data: {\"choices\":[{\"delta\":{\"content\":\"GW_NATIVE_OK\",\"reasoning_content\":\"Check first\"},\"finish_reason\":\"stop\"}],\"usage\":{\"prompt_tokens\":100,\"completion_tokens\":7}}\n\ndata: [DONE]\n\n"
			}
			response := &http.Response{Header: http.Header{"Content-Type": []string{contentType}}, Body: io.NopCloser(strings.NewReader(body))}
			capture := &nativeUsageCapture{protocol: "openai-completions", stream: stream}
			writer := httptest.NewRecorder()
			if _, err := bridge.forward(writer, response, capture); err != nil {
				t.Fatal(err)
			}
			var blocks []string
			for _, line := range strings.Split(writer.Body.String(), "\n") {
				if !strings.HasPrefix(line, "data: ") {
					continue
				}
				var event map[string]any
				_ = json.Unmarshal([]byte(line[6:]), &event)
				if event["type"] == "content_block_start" {
					blocks = append(blocks, fieldText(objectValue(event["content_block"]), "type"))
				}
			}
			if strings.Join(blocks, ",") != "thinking,text" || !strings.Contains(writer.Body.String(), "GW_NATIVE_OK") || !strings.Contains(writer.Body.String(), "message_stop") {
				t.Fatalf("CC must receive final text after thinking: %v", blocks)
			}
		})
	}
}

func TestGatewayRejectsThinkingThatArrivesAfterCCText(t *testing.T) {
	w := httptest.NewRecorder()
	e := newProtocolEncoder(w, &protocolBridge{from: "anthropic-messages", request: protocolRequest{Stream: true}})
	if err := e.textWithReasoning("answer", ""); err != nil {
		t.Fatal(err)
	}
	r := newProtocolResult()
	r.Text, r.Reasoning = "answer", "late thought"
	if err := e.finish(r, &Usage{100, 7, 0}); err == nil || strings.Contains(w.Body.String(), "message_stop") {
		t.Fatal("late reasoning must not replace a successful CC final reply")
	}
}

func TestGatewayDoesNotForceVendorThinkingDefaultsOnUnrelatedModels(t *testing.T) {
	for _, format := range []string{"anthropic-messages", "openai-responses"} {
		request := protocolFixtureRequest(format, true)
		if format == "anthropic-messages" {
			request["thinking"] = map[string]any{"type": "adaptive"}
			request["output_config"] = map[string]any{"effort": "high"}
		} else {
			request["reasoning"] = map[string]any{"effort": "high", "summary": "auto"}
		}
		body, _ := json.Marshal(request)
		converted, bridge, err := prepareProtocolBridge(body, format, "openai-completions", "fixture")
		if err != nil {
			t.Fatal(err)
		}
		var raw map[string]any
		_ = json.Unmarshal(converted, &raw)
		if raw["reasoning_effort"] != nil || raw["thinking"] != nil || raw["reasoning"] != nil {
			t.Fatal("provider-specific defaults were forced on the upstream")
		}
		writer := httptest.NewRecorder()
		_ = newProtocolEncoder(writer, bridge)
		if writer.Header().Get("X-Roami-Unsupported-Parameters") == "" {
			t.Fatal("unsupported vendor settings were hidden")
		}
	}
	request := protocolFixtureRequest("openai-completions", false)
	request["reasoning_effort"] = "low"
	body, _ := json.Marshal(request)
	converted, _, err := prepareProtocolBridge(body, "openai-completions", "openai-responses", "fixture")
	if err != nil {
		t.Fatal(err)
	}
	var raw map[string]any
	_ = json.Unmarshal(converted, &raw)
	if fieldText(objectValue(raw["reasoning"]), "effort") != "low" {
		t.Fatal("an explicitly saved Chat reasoning setting was lost")
	}
}
