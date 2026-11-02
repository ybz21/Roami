package modelgateway

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func saveNodeModels(t *testing.T, ledger *Ledger, value any) string {
	t.Helper()
	path := filepath.Join(ledger.paths.Data, "agents", "model-settings.json")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func nodeConfiguredHandler(t *testing.T, ledger *Ledger, target string) *Handler {
	t.Helper()
	saveNodeModels(t, ledger, map[string]any{
		"connection": map[string]string{"baseUrl": target + "/custom/v1", "apiKey": "node-key"},
		"main":       map[string]string{"model": "fixture"},
		"worker":     map[string]string{"model": "fixture"},
	})
	return NewHandler(ledger)
}

func TestNodeOwnsUpstreamAndCredentials(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	var hits, rogueHits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if r.Header.Get("Authorization") != "Bearer node-key" || r.Header.Get("X-Api-Key") != "" || r.Header.Get("X-Roami-Model-Route") != "" {
			t.Error("caller credential or private route leaked")
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, billableEvents)
	}))
	defer upstream.Close()
	rogue := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { rogueHits.Add(1) }))
	defer rogue.Close()
	handler := nodeConfiguredHandler(t, ledger, upstream.URL)
	request := modelRequest(rogue.URL)
	request.Header.Set("X-Api-Key", "caller-key")
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != 200 || hits.Load() != 1 || rogueHits.Load() != 0 {
		t.Fatalf("caller selected upstream: code=%d hits=%d rogue=%d", response.Code, hits.Load(), rogueHits.Load())
	}
}

func TestNodeRejectsModelParameterAndStaleRouteBeforeAdmission(t *testing.T) {
	for _, test := range []struct{ name, body, role, identity string }{
		{"arbitrary model", `{"model":"other"}`, "worker", ""},
		{"caller cap", `{"model":"fixture","max_tokens":10}`, "worker", ""},
		{"caller temperature", `{"model":"fixture","temperature":0}`, "worker", ""},
		{"stale endpoint", `{"model":"fixture"}`, "worker", strings.Repeat("a", 64)},
		{"invalid role", `{"model":"fixture"}`, "artifact_a", ""},
	} {
		t.Run(test.name, func(t *testing.T) {
			ledger := newLedger(t)
			if err := ledger.Configure(testConfiguration(nil)); err != nil {
				t.Fatal(err)
			}
			var hits atomic.Int32
			up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { hits.Add(1) }))
			defer up.Close()
			handler := nodeConfiguredHandler(t, ledger, up.URL)
			request := httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(test.body))
			request.Header.Set("X-Roami-Model-Role", test.role)
			request.Header.Set("X-Roami-Model-Route", test.identity)
			response := httptest.NewRecorder()
			handler.ServeHTTP(response, request)
			stats, err := ledger.Statistics(1)
			if response.Code < 400 || hits.Load() != 0 || err != nil || len(stats.Recent) != 0 {
				t.Fatalf("rejection dispatched or charged: status=%d hits=%d stats=%+v err=%v", response.Code, hits.Load(), stats, err)
			}
		})
	}
}

func TestNodeRoleConfigurationAndSavedConnection(t *testing.T) {
	ledger := newLedger(t)
	config := `[model]
endpoint = "https://main.invalid/v1"
name = "main"
key_env = "NODE_MAIN_KEY"
[model.parameters]
max_tokens = 8192
temperature = 0.4
[worker.model]
name = "worker"
key_env = "NODE_WORKER_KEY"
`
	if err := os.WriteFile(filepath.Join(ledger.paths.Home, "agent.toml"), []byte(config), 0600); err != nil {
		t.Fatal(err)
	}
	t.Setenv("NODE_MAIN_KEY", "main-credential")
	t.Setenv("NODE_WORKER_KEY", "worker-credential")
	main, err := readNodeModels(ledger.paths, "main")
	if err != nil || main.model != "main" || main.key != "main-credential" || main.parameters["max_tokens"] != float64(8192) {
		t.Fatalf("main route: %+v %v", main, err)
	}
	worker, err := readNodeModels(ledger.paths, "memory")
	if err != nil || worker.model != "worker" || worker.key != "worker-credential" || len(worker.parameters) != 0 {
		t.Fatalf("worker inherited main parameters: %+v %v", worker, err)
	}
	saveNodeModels(t, ledger, map[string]any{"connection": map[string]string{"baseUrl": "https://saved.invalid/v1/", "apiKey": "saved-credential"}, "worker": map[string]any{"model": "saved-worker", "reasoningEffort": "high"}})
	worker, err = readNodeModels(ledger.paths, "worker")
	if err != nil || worker.endpoint != "https://saved.invalid/v1" || worker.model != "saved-worker" || worker.key != "saved-credential" || worker.parameters["reasoning_effort"] != "high" {
		t.Fatalf("saved route not applied: %+v %v", worker, err)
	}
	if !worker.accepts(map[string]any{"model": "saved-worker", "reasoning_effort": "high"}, worker.identity()) || worker.accepts(map[string]any{"model": "saved-worker"}, "") {
		t.Fatal("configured parameters not pinned")
	}
}

func TestNodeConfigurationFailsClosed(t *testing.T) {
	for _, mode := range []string{"missing", "public", "malformed", "symlink", "insecure endpoint"} {
		t.Run(mode, func(t *testing.T) {
			ledger := newLedger(t)
			path := saveNodeModels(t, ledger, map[string]any{"main": map[string]string{"model": "fixture", "baseUrl": "https://saved.invalid/v1"}})
			switch mode {
			case "missing":
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
			case "public":
				if err := os.Chmod(path, 0644); err != nil {
					t.Fatal(err)
				}
			case "malformed":
				if err := os.WriteFile(path, []byte("{"), 0600); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.Rename(path, path+".real"); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(path+".real", path); err != nil {
					t.Fatal(err)
				}
			case "insecure endpoint":
				saveNodeModels(t, ledger, map[string]any{"main": map[string]string{"model": "fixture", "baseUrl": "http://external.invalid/v1"}})
			}
			response := httptest.NewRecorder()
			NewHandler(ledger).ServeHTTP(response, modelRequest("https://caller.invalid"))
			stats, err := ledger.Statistics(1)
			if response.Code != 503 || err != nil || len(stats.Recent) != 0 {
				t.Fatalf("invalid config admitted: %d %+v %v", response.Code, stats, err)
			}
		})
	}
}

func TestQueuedRequestRechecksSavedRouteBeforeAdmission(t *testing.T) {
	ledger := newLedger(t)
	if err := ledger.Configure(testConfiguration(floatPointer(10))); err != nil {
		t.Fatal(err)
	}
	entered, release := make(chan struct{}), make(chan struct{})
	var once sync.Once
	unblock := func() { once.Do(func() { close(release) }) }
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		close(entered)
		<-release
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, billableEvents)
	}))
	defer upstream.Close()
	defer unblock()
	handler := nodeConfiguredHandler(t, ledger, upstream.URL)
	firstDone, secondDone := make(chan struct{}), make(chan struct{})
	go func() { defer close(firstDone); handler.ServeHTTP(httptest.NewRecorder(), modelRequest(upstream.URL)) }()
	awaitAdmission(t, entered)
	second := httptest.NewRecorder()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	go func() {
		defer close(secondDone)
		handler.ServeHTTP(second, modelRequest(upstream.URL).WithContext(ctx))
	}()
	select {
	case <-secondDone:
		t.Fatal("request did not wait for the active receipt")
	case <-time.After(50 * time.Millisecond):
	}
	saveNodeModels(t, ledger, map[string]any{"connection": map[string]string{"baseUrl": upstream.URL + "/custom/v1", "apiKey": "updated-node-key"}, "worker": map[string]string{"model": "new-selected-model"}})
	unblock()
	awaitAdmission(t, firstDone)
	awaitAdmission(t, secondDone)
	stats, err := ledger.Statistics(1)
	if second.Code != 409 || second.Header().Get("X-Roami-Model-Error") != "MODEL_GATEWAY_ROUTE_CHANGED" || hits.Load() != 1 || err != nil || len(stats.Recent) != 1 {
		t.Fatalf("stale queued request sent or charged: %d hits=%d stats=%+v err=%v", second.Code, hits.Load(), stats, err)
	}
}
