package modelgateway

import (
	"context"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

func catalogHandler(t *testing.T, upstream, protocol string) *Handler {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("CODEX_HOME", filepath.Join(home, ".codex"))
	t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(home, ".claude"))
	t.Setenv("PI_CODING_AGENT_DIR", filepath.Join(home, ".pi"))
	t.Setenv("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
	t.Setenv("OPENCODE_CONFIG", filepath.Join(home, "opencode.json"))
	t.Setenv("OPENCODE_CONFIG_CONTENT", "")
	bin := filepath.Join(home, "bin")
	_ = os.Mkdir(bin, 0700)
	_ = os.WriteFile(filepath.Join(bin, "opencode"), []byte("#!/bin/sh\necho 2.0.0\n"), 0700)
	t.Setenv("PATH", bin)
	l := newLedger(t)
	s, err := openCatalog(l)
	if err != nil {
		t.Fatal(err)
	}
	s.baseURL = "http://127.0.0.1:19999"
	value := s.snapshot()
	value.Sources = []ModelSource{{ID: "work", Name: "Work", BaseURL: upstream, Protocol: protocol, AuthMode: "bearer", APIKey: "upstream-secret"}}
	value.Models = []CatalogModel{{ID: "coding-main", Name: "Coding", Protocol: protocol, Strategy: "fixed", Candidates: []ModelCandidate{{"work", "fixture"}}}}
	if err = s.update(context.Background(), value); err != nil {
		t.Fatal(err)
	}
	h := NewHandler(l)
	h.Catalog = s
	return h
}
func catalogRequest(h *Handler, path, body string) *httptest.ResponseRecorder {
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", path, strings.NewReader(body))
	r.Header.Set("Authorization", "Bearer "+h.Catalog.credential("codex"))
	r.Header.Set("X-Roami-Owner", "private-owner")
	r.Header.Set("Cookie", "private-cookie")
	h.publicModels(w, r)
	return w
}
func TestCatalogSecretsRevisionDraftAndConfigurationPreservation(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-responses")
	s := h.Catalog
	cfg := testConfiguration(nil)
	if err := h.Ledger.Configure(cfg); err != nil {
		t.Fatal(err)
	}
	view := s.view(context.Background())
	raw, _ := json.Marshal(view)
	if strings.Contains(string(raw), "upstream-secret") || strings.Contains(string(raw), s.value.Token) || !view.Sources[0].HasKey {
		t.Fatal("secret escaped summary")
	}
	view.Drafts = []CatalogModel{{ID: "draft", Name: "Draft", Protocol: "openai-responses", Strategy: "fixed", Candidates: []ModelCandidate{{"work", "next"}}}}
	if err := s.update(context.Background(), view); err != nil {
		t.Fatal(err)
	}
	if s.value.Sources[0].APIKey != "upstream-secret" || len(s.value.Models) != 1 || s.value.Models[0].ID != "coding-main" {
		t.Fatal("saving a draft changed the live route or credential")
	}
	if err := s.update(context.Background(), view); err == nil || err.Error() != "MODEL_CATALOG_CHANGED" {
		t.Fatalf("stale revision accepted: %v", err)
	}
	after, _ := h.Ledger.Configuration()
	if after.Pricing.Models["fixture"] != cfg.Pricing.Models["fixture"] {
		t.Fatal("catalog update changed pricing")
	}
	changed := s.view(context.Background())
	changed.Sources[0].BaseURL = "https://different.example/v1"
	if err := s.update(context.Background(), changed); err == nil || err.Error() != "MODEL_KEY_REQUIRED_FOR_ENDPOINT" {
		t.Fatalf("reused key across endpoints: %v", err)
	}
}
func TestNativeGatewayForwardsToolEventsAndUsesExistingModelPrices(t *testing.T) {
	events := "event: response.output_item.added\ndata: {\"type\":\"response.output_item.added\",\"item\":{\"type\":\"function_call\",\"name\":\"fixture_tool\",\"arguments\":\"{}\"}}\n\nevent: response.completed\ndata: {\"type\":\"response.completed\",\"response\":{\"usage\":{\"input_tokens\":1000000,\"output_tokens\":125000,\"input_tokens_details\":{\"cached_tokens\":500000}}}}\n\n"
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		body, _ := io.ReadAll(r.Body)
		var value map[string]any
		_ = json.Unmarshal(body, &value)
		if value["model"] != "fixture" || !strings.Contains(string(body), "function_call_output") || r.URL.Path != "/v1/responses" || r.Header.Get("Authorization") != "Bearer upstream-secret" || r.Header.Get("Cookie") != "" || r.Header.Get("X-Roami-Owner") != "" {
			t.Error("payload, path or credential isolation failed")
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, events)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL+"/v1", "openai-responses")
	limit := 2.0
	_ = h.Ledger.Configure(testConfiguration(&limit))
	body := `{"model":"coding-main","stream":true,"input":[{"type":"function_call_output","call_id":"call-1","output":"fixture"}]}`
	w := catalogRequest(h, "/v1/responses", body)
	if w.Code != 200 || w.Body.String() != events || !w.Flushed {
		t.Fatalf("stream changed: %d %s", w.Code, w.Body.String())
	}
	stats, err := h.Ledger.Statistics(1)
	if err != nil || len(stats.Today) != 1 || stats.Today[0].Model != "fixture" || stats.Today[0].Cost != "2.000000000" {
		t.Fatalf("pricing lost: %+v %v", stats, err)
	}
	w = catalogRequest(h, "/v1/responses", body)
	if w.Code != 402 || hits.Load() != 1 {
		t.Fatal("daily limit bypassed")
	}
	w = catalogRequest(h, "/v1/responses", `{"model":"coding-main","previous_response_id":"provider-bound-id"}`)
	if w.Code != 400 || hits.Load() != 1 {
		t.Fatal("stateful continuation routed to an arbitrary provider")
	}
	r := httptest.NewRequest("GET", "/v1/model-gateway/catalog", nil)
	r.Header.Set("Authorization", "Bearer "+h.Catalog.credential("codex"))
	w = httptest.NewRecorder()
	h.publicModels(w, r)
	if w.Code != 404 {
		t.Fatal("management exposed on inference listener")
	}
}
func TestNativeGatewayFailoverOnlyBeforeConnectionAndKeepsUnknownCharges(t *testing.T) {
	for _, mode := range []string{"dial", "server-error", "partial"} {
		t.Run(mode, func(t *testing.T) {
			var backupHits atomic.Int32
			backup := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				backupHits.Add(1)
				_, _ = io.WriteString(w, `{"status":"completed","usage":{"input_tokens":5,"output_tokens":3}}`)
			}))
			defer backup.Close()
			primary := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if mode == "server-error" {
					w.WriteHeader(500)
					return
				}
				w.Header().Set("Content-Type", "text/event-stream")
				_, _ = io.WriteString(w, "data: {\"type\":\"response.output_text.delta\",\"delta\":\"started\"}\n\n")
			}))
			defer primary.Close()
			if mode == "dial" {
				primary.Close()
			}
			h := catalogHandler(t, primary.URL, "openai-responses")
			_ = h.Ledger.Configure(testConfiguration(nil))
			s := h.Catalog
			s.value.Sources = append(s.value.Sources, ModelSource{ID: "backup", Name: "Backup", BaseURL: backup.URL, Protocol: "openai-responses", AuthMode: "bearer"})
			s.value.Models[0].Strategy = "failover"
			s.value.Models[0].Candidates = append(s.value.Models[0].Candidates, ModelCandidate{"backup", "fixture"})
			w := catalogRequest(h, "/v1/responses", `{"model":"coding-main","stream":true}`)
			stats, _ := h.Ledger.Statistics(1)
			if mode == "dial" {
				if backupHits.Load() != 1 || w.Code != 200 || len(stats.Recent) != 2 {
					t.Fatalf("dial failover: %d %d %+v", w.Code, backupHits.Load(), stats)
				}
			} else {
				if backupHits.Load() != 0 || len(stats.Recent) != 1 || stats.Recent[0].State != "unknown" {
					t.Fatalf("unsafe replay or lost unknown: %+v", stats)
				}
			}
		})
	}
}
func TestCatalogApplyUsesNativeBackupAndNeverCopiesUpstreamKey(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-responses")
	s := h.Catalog
	path := filepath.Join(os.Getenv("CODEX_HOME"), "config.toml")
	_ = os.MkdirAll(filepath.Dir(path), 0700)
	_ = os.WriteFile(path, []byte("model='original'\n[mcp_servers.keep]\ncommand='keep-command'\n"), 0600)
	view, err := s.agents.View(context.Background(), "codex")
	if err != nil {
		t.Fatal(err)
	}
	wrong, _ := json.Marshal(map[string]string{"kind": "codex", "sourceId": "not-the-model-source", "model": "coding-main", "revision": view.Revision, "catalogRevision": s.value.Revision})
	rejected := httptest.NewRecorder()
	h.ServeHTTP(rejected, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(wrong))))
	if rejected.Code != 400 {
		t.Fatal("accepted a mismatched source and model")
	}
	unchanged, _ := os.ReadFile(path)
	if !strings.Contains(string(unchanged), "model='original'") {
		t.Fatal("invalid source changed native settings")
	}
	body, _ := json.Marshal(map[string]string{"kind": "codex", "model": "coding-main", "revision": view.Revision, "catalogRevision": s.value.Revision})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(body))))
	if w.Code != 200 {
		t.Fatalf("apply: %d %s", w.Code, w.Body.String())
	}
	raw, _ := os.ReadFile(path)
	if strings.Contains(string(raw), "upstream-secret") || !strings.Contains(string(raw), "keep-command") || !strings.Contains(string(raw), "coding-main") {
		t.Fatalf("native config damaged or leaked")
	}
	applied, _ := s.agents.View(context.Background(), "codex")
	if !applied.CanRestore {
		t.Fatal("original config not backed up")
	}
	value := s.view(context.Background())
	value.Models = nil
	if err := s.update(context.Background(), value); err == nil || err.Error() != "MODEL_CATALOG_IN_USE" {
		t.Fatalf("removed bound alias: %v", err)
	}
	restored, err := s.agents.Restore(context.Background(), "codex", applied.Revision)
	if err != nil || restored.Current.Model != "original" {
		t.Fatalf("restore: %+v %v", restored, err)
	}
}

func TestMessagesUsageSplitEventsAndMissingTerminal(t *testing.T) {
	events := "data: {\"type\":\"message_start\",\"message\":{\"usage\":{\"input_tokens\":10,\"output_tokens\":0,\"cache_read_input_tokens\":6,\"cache_creation_input_tokens\":4}}}\n\ndata: {\"type\":\"message_delta\",\"usage\":{\"output_tokens\":8}}\n\ndata: {\"type\":\"message_stop\"}\n\n"
	c := nativeUsageCapture{protocol: "anthropic-messages", stream: true}
	for _, b := range []byte(events) {
		c.feed([]byte{b})
	}
	usage := c.finish(true)
	if usage == nil || usage.Input != 20 || usage.Cached != 6 || usage.Output != 8 {
		t.Fatalf("bad Messages accounting: %+v", usage)
	}
	c = nativeUsageCapture{protocol: "anthropic-messages", stream: true}
	c.feed([]byte(strings.ReplaceAll(events, "data: {\"type\":\"message_stop\"}\n\n", "")))
	if c.finish(true) != nil {
		t.Fatal("missing terminal was treated as complete")
	}
}

func TestRoamiBindingUsesRuntimeSaveRestoresOriginalAndBillsOnce(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body["model"] != "fixture" || r.Header.Get("Authorization") != "Bearer upstream-secret" {
			t.Error("runtime route was not resolved")
		}
		_, _ = io.WriteString(w, `{"usage":{"prompt_tokens":1000000,"completion_tokens":125000,"prompt_tokens_details":{"cached_tokens":500000}}}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	s := h.Catalog
	_ = h.Ledger.Configure(testConfiguration(nil))
	saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]string{"baseUrl": upstream.URL, "apiKey": "original-key"}, "main": map[string]any{"model": "old-main", "images": true}, "worker": map[string]any{"model": "old-worker"}})
	root, err := os.MkdirTemp("", "roami-role-ipc-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(root)
	s.agentSocket = filepath.Join(root, "agent.sock")
	listener, err := net.Listen("unix", s.agentSocket)
	if err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	current := map[string]any{"main": map[string]any{"model": "old-main", "images": true, "configuredContextWindow": 1000}, "worker": map[string]any{"model": "old-worker", "images": false, "configuredContextWindow": nil}}
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		defer mu.Unlock()
		if r.Header.Get("X-Roami-Owner") != "local" || r.URL.Path != "/v1/model-settings" {
			t.Error("incorrect runtime IPC")
		}
		if r.Method == "PUT" {
			var patch map[string]any
			if json.NewDecoder(r.Body).Decode(&patch) != nil {
				w.WriteHeader(400)
				return
			}
			saveNodeModels(t, h.Ledger, patch)
			current = patch
		}
		writeJSON(w, 200, map[string]any{"data": current})
	})}
	go server.Serve(listener)
	defer server.Close()
	apply := func(restore bool) *httptest.ResponseRecorder {
		body, _ := json.Marshal(map[string]any{"main": "coding-main", "worker": "coding-main", "revision": s.value.Revision, "restore": restore})
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/roles", strings.NewReader(string(body))))
		return w
	}
	if w := apply(false); w.Code != 200 {
		t.Fatalf("runtime binding: %d %s", w.Code, w.Body.String())
	}
	main, err := readNodeModels(h.Ledger.paths, "main")
	if err != nil || main.endpoint != s.baseURL+"/v1" || main.model != "coding-main" {
		t.Fatalf("runtime save did not land: %+v %v", main, err)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(`{"model":"coding-main","messages":[{"role":"user","content":"fixture"}]}`)))
	stats, _ := h.Ledger.Statistics(1)
	if w.Code != 200 || len(stats.Recent) != 1 || stats.Recent[0].Role != "main" || stats.Today[0].Cost != "2.000000000" {
		t.Fatalf("double billing or wrong route: %d %+v", w.Code, stats)
	}
	if w := apply(true); w.Code != 200 {
		t.Fatalf("runtime restore: %d %s", w.Code, w.Body.String())
	}
	main, _ = readNodeModels(h.Ledger.paths, "main")
	if main.model != "old-main" || main.key != "original-key" || main.endpoint != upstream.URL {
		t.Fatal("original connection was not restored")
	}
}

func TestFactoryModeHidesInactiveConsumerButKeepsPresetReferences(t *testing.T) {
	for _, test := range []struct{ kind, protocol string }{{"codex", "openai-responses"}, {"claude", "anthropic-messages"}} {
		t.Run(test.kind, func(t *testing.T) {
			h := catalogHandler(t, "https://upstream.example/v1", test.protocol)
			s := h.Catalog
			view, err := s.agents.View(context.Background(), test.kind)
			if err != nil {
				t.Fatal(err)
			}
			body, _ := json.Marshal(map[string]string{"kind": test.kind, "sourceId": "work", "model": "coding-main", "revision": view.Revision, "catalogRevision": s.value.Revision})
			w := httptest.NewRecorder()
			h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(body))))
			if w.Code != 200 {
				t.Fatalf("apply: %d %s", w.Code, w.Body)
			}
			if len(s.uses(context.Background())["coding-main"]) != 1 {
				t.Fatal("active gateway consumer missing")
			}
			custom, err := s.agents.View(context.Background(), test.kind)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = s.agents.UseOfficial(context.Background(), test.kind, custom.Revision); err != nil {
				t.Fatal(err)
			}
			if len(s.uses(context.Background())["coding-main"]) != 0 {
				t.Fatal("factory mode still reported as using custom model")
			}
			refs, _ := s.references(context.Background())
			if len(refs["coding-main"]) != 1 {
				t.Fatal("factory mode discarded saved custom preset references")
			}
		})
	}
}

func TestSavedSourceDiscoveryIsReadOnlyAndKeepsCredentialsPrivate(t *testing.T) {
	hits := atomic.Int32{}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if r.URL.Path != "/v1/models" || r.Header.Get("Authorization") != "Bearer upstream-secret" {
			t.Error("source credentials or endpoint mismatch")
		}
		_, _ = io.WriteString(w, `{"data":[{"id":"vendor/new-model"},{"id":"upstream-secret"}]}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "anthropic-messages")
	s := h.Catalog
	next := s.snapshot()
	next.Models = []CatalogModel{}
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	request := func(kind string) *httptest.ResponseRecorder {
		body, _ := json.Marshal(map[string]string{"kind": kind, "sourceId": "work", "revision": s.value.Revision})
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/source-models", strings.NewReader(string(body))))
		return w
	}
	w := request("claude")
	if w.Code != 200 || !strings.Contains(w.Body.String(), "vendor/new-model") || strings.Contains(w.Body.String(), "upstream-secret") {
		t.Fatalf("discovery: %d %s", w.Code, w.Body)
	}
	if len(s.value.Models) != 0 {
		t.Fatal("reading a source created a model route")
	}
	if _, err := os.Stat(filepath.Join(os.Getenv("CLAUDE_CONFIG_DIR"), "settings.json")); !os.IsNotExist(err) {
		t.Fatal("reading a source changed CLI settings")
	}
	if wrong := request("unknown"); wrong.Code != 400 || hits.Load() != 1 {
		t.Fatal("incompatible discovery contacted the source")
	}
}

func TestSourceOnlyModelSelectionCreatesReusableRouteOnApply(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var body struct {
			Model string `json:"model"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		if body.Model != "vendor/new-model" || r.Header.Get("Authorization") != "Bearer upstream-secret" {
			t.Error("source model forwarding mismatch")
		}
		_, _ = io.WriteString(w, `{"type":"message","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":10,"output_tokens":2},"stop_reason":"end_turn"}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "anthropic-messages")
	s := h.Catalog
	next := s.snapshot()
	next.Models = []CatalogModel{}
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	apply := func() *httptest.ResponseRecorder {
		view, err := s.agents.View(context.Background(), "claude")
		if err != nil {
			t.Fatal(err)
		}
		body, _ := json.Marshal(map[string]string{"kind": "claude", "sourceId": "work", "upstreamModel": "vendor/new-model", "revision": view.Revision, "catalogRevision": s.value.Revision})
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(body))))
		return w
	}
	if w := apply(); w.Code != 200 || strings.Contains(w.Body.String(), "upstream-secret") {
		t.Fatalf("apply source model: %d %s", w.Code, w.Body)
	}
	if len(s.value.Models) != 1 || s.value.Models[0].Name != "vendor/new-model" || s.value.Models[0].Candidates[0].SourceID != "work" {
		t.Fatal("selected source model was not registered")
	}
	routeID := s.value.Models[0].ID
	if w := apply(); w.Code != 200 || len(s.value.Models) != 1 || s.value.Models[0].ID != routeID {
		t.Fatal("reapplying the same source model created a duplicate")
	}
	raw, _ := os.ReadFile(filepath.Join(os.Getenv("CLAUDE_CONFIG_DIR"), "settings.json"))
	if strings.Contains(string(raw), "upstream-secret") || !strings.Contains(string(raw), routeID) {
		t.Fatal("source credential leaked into CLI or route missing")
	}
	w := httptest.NewRecorder()
	r := httptest.NewRequest("POST", "/v1/messages", strings.NewReader(`{"model":"`+routeID+`","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}`))
	r.Header.Set("Authorization", "Bearer "+s.credential("claude"))
	h.publicModels(w, r)
	if w.Code != 200 || !strings.Contains(w.Body.String(), `"text":"ok"`) {
		t.Fatalf("selected model cannot be used: %d %s", w.Code, w.Body)
	}
}

func TestNativeModelChangesRemainProtectedAfterCliSelection(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-responses")
	s := h.Catalog
	next := s.snapshot()
	second := next.Models[0]
	second.ID = "coding-other"
	next.Models = append(next.Models, second)
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	view, err := s.agents.View(context.Background(), "codex")
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(map[string]string{"kind": "codex", "model": "coding-main", "revision": view.Revision, "catalogRevision": s.value.Revision})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(body))))
	if w.Code != 200 {
		t.Fatal(w.Body)
	}
	path := filepath.Join(os.Getenv("CODEX_HOME"), "config.toml")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, []byte(strings.Replace(string(raw), "coding-main", "coding-other", 1)), 0600); err != nil {
		t.Fatal(err)
	}
	if len(s.uses(context.Background())["coding-other"]) != 1 {
		t.Fatal("native model selection was not shown as in use")
	}
	next = s.snapshot()
	next.Models = next.Models[:1]
	if err = s.update(context.Background(), next); err == nil || err.Error() != "MODEL_CATALOG_IN_USE" {
		t.Fatal("deleted a model selected by the CLI")
	}
}
