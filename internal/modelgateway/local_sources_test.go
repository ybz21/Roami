package modelgateway

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func localSourcesResponse(t *testing.T, h *Handler) []localSourceView {
	t.Helper()
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/catalog/local-sources", nil))
	var result struct {
		Data struct {
			Sources []localSourceView `json:"sources"`
		} `json:"data"`
	}
	if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &result) != nil {
		t.Fatalf("local sources %d %s", w.Code, w.Body)
	}
	if strings.Contains(w.Body.String(), "fixture-local-secret") || strings.Contains(w.Body.String(), "fixture-environment-secret") {
		t.Fatal("local key leaked to browser")
	}
	return result.Data.Sources
}
func TestLocalSourceImportIsExplicitPrivateAndDoesNotChangeNativeConfiguration(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example", "openai-completions")
	native := `{"model":"work/native-model","mcp":{"keep":{"command":"fixture"}},"providers":{"work":{"package":"@opencode/ai/providers/openai-compatible","settings":{"baseURL":"https://local.example/v1","apiKey":"fixture-local-secret"}}}}`
	_ = os.WriteFile(os.Getenv("OPENCODE_CONFIG"), []byte(native), 0600)
	rows := localSourcesResponse(t, h)
	if len(rows) != 1 || rows[0].Unavailable || !rows[0].HasKey || rows[0].Model != "native-model" {
		t.Fatalf("missing source %+v", rows)
	}
	if len(h.Catalog.value.Sources) != 1 {
		t.Fatal("reading sources imported credentials")
	}
	body, _ := json.Marshal(map[string]string{"id": rows[0].ID, "revision": rows[0].Revision, "catalogRevision": h.Catalog.value.Revision})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/local-sources", strings.NewReader(string(body))))
	if w.Code != 200 || strings.Contains(w.Body.String(), "fixture-local-secret") {
		t.Fatalf("import %d %s", w.Code, w.Body)
	}
	saved := h.Catalog.value.Sources[1]
	if saved.APIKey != "fixture-local-secret" || saved.BaseURL != "https://local.example/v1" {
		t.Fatal("import did not preserve source")
	}
	after, _ := os.ReadFile(os.Getenv("OPENCODE_CONFIG"))
	if string(after) != native {
		t.Fatal("import rewrote native config")
	}
	rows = localSourcesResponse(t, h)
	body, _ = json.Marshal(map[string]string{"id": rows[0].ID, "revision": rows[0].Revision, "catalogRevision": h.Catalog.value.Revision})
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/local-sources", strings.NewReader(string(body))))
	if w.Code != 409 || len(h.Catalog.value.Sources) != 2 {
		t.Fatal("duplicate source silently overwrote catalog")
	}
}
func TestLocalImportEnvironmentMissingDynamicAndRecursiveCredentials(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example", "openai-completions")
	t.Setenv("LOCAL_SOURCE_KEY", "fixture-environment-secret")
	native := `{"providers":{"env":{"package":"@opencode/ai/providers/openai-compatible","settings":{"baseURL":"https://env.example/v1","apiKey":"{env:LOCAL_SOURCE_KEY}"}},"missing":{"package":"@opencode/ai/providers/openai-compatible","settings":{"baseURL":"https://missing.example/v1","apiKey":"{env:UNSET_FIXTURE_KEY}"}},"recursive":{"package":"@opencode/ai/providers/openai-compatible","settings":{"baseURL":"http://localhost:19999/v1/","apiKey":"local-gateway-key"}}}}`
	_ = os.WriteFile(os.Getenv("OPENCODE_CONFIG"), []byte(native), 0600)
	rows := localSourcesResponse(t, h)
	if len(rows) != 2 {
		t.Fatalf("recursive source was offered %+v", rows)
	}
	var env localSourceView
	for _, row := range rows {
		if row.Name == "missing" && !row.Unavailable {
			t.Fatal("missing credential accepted")
		}
		if row.Name == "env" {
			env = row
		}
	}
	t.Setenv("LOCAL_SOURCE_KEY", "fixture-changed-secret")
	body, _ := json.Marshal(map[string]string{"id": env.ID, "revision": env.Revision, "catalogRevision": h.Catalog.value.Revision})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/local-sources", strings.NewReader(string(body))))
	if w.Code != 409 {
		t.Fatal("environment changed after preview but import was not rejected")
	}
}

func TestImportedAnthropicSourceUsesNativeAPIKeyHeader(t *testing.T) {
	for _, kind := range []string{"opencode-v1", "opencode-v2", "pi"} {
		t.Run(kind, func(t *testing.T) {
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Header.Get("X-Api-Key") != "fixture-anthropic-key" || r.Header.Get("Authorization") != "" {
					t.Error("native API key imported as bearer token")
					w.WriteHeader(401)
					return
				}
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(`{"data":[{"id":"fixture-model"}],"has_more":false}`))
			}))
			defer upstream.Close()
			h := catalogHandler(t, "https://existing.example", "openai-completions")
			var path, native string
			switch kind {
			case "opencode-v1":
				path, native = os.Getenv("OPENCODE_CONFIG"), fmt.Sprintf(`{"provider":{"work":{"npm":"@ai-sdk/anthropic","options":{"baseURL":%q,"apiKey":"fixture-anthropic-key"}}}}`, upstream.URL)
			case "opencode-v2":
				path, native = os.Getenv("OPENCODE_CONFIG"), fmt.Sprintf(`{"providers":{"work":{"package":"@opencode/ai/providers/anthropic-compatible","settings":{"baseURL":%q,"apiKey":"fixture-anthropic-key"}}}}`, upstream.URL)
			case "pi":
				path, native = filepath.Join(os.Getenv("PI_CODING_AGENT_DIR"), "models.json"), fmt.Sprintf(`{"providers":{"work":{"api":"anthropic-messages","baseUrl":%q,"apiKey":"fixture-anthropic-key"}}}`, upstream.URL)
			}
			_ = os.MkdirAll(filepath.Dir(path), 0700)
			_ = os.WriteFile(path, []byte(native), 0600)
			rows := localSourcesResponse(t, h)
			if len(rows) != 1 || rows[0].Unavailable {
				t.Fatalf("source unavailable: %+v", rows)
			}
			input, _ := json.Marshal(map[string]string{"id": rows[0].ID, "revision": rows[0].Revision, "catalogRevision": h.Catalog.value.Revision})
			w := httptest.NewRecorder()
			h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/local-sources", strings.NewReader(string(input))))
			if w.Code != 200 {
				t.Fatalf("import failed: %d %s", w.Code, w.Body)
			}
			source := h.Catalog.view(context.Background()).Sources[1]
			body, _ := json.Marshal(map[string]any{"source": source, "revision": h.Catalog.value.Revision})
			w = httptest.NewRecorder()
			h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/discover", strings.NewReader(string(body))))
			if w.Code != 200 || !strings.Contains(w.Body.String(), "fixture-model") {
				t.Fatalf("discovery failed: %d %s", w.Code, w.Body)
			}
		})
	}
}
