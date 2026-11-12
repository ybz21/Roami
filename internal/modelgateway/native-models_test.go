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
	"testing"
)

func TestNativeAgentDefaultsAndCompleteModelCatalogs(t *testing.T) {
	for _, kind := range []string{"pi", "opencode", "codex"} {
		t.Run(kind, func(t *testing.T) {
			var got string
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				var body struct{ Model string }
				_ = json.NewDecoder(r.Body).Decode(&body)
				got = body.Model
				_, _ = io.WriteString(w, `{"id":"fixture","choices":[{"message":{"role":"assistant","content":"OK"},"finish_reason":"stop"}],"usage":{"prompt_tokens":10,"completion_tokens":2}}`)
			}))
			defer upstream.Close()
			h := catalogHandler(t, upstream.URL, "openai-completions")
			s := h.Catalog
			second := s.value.Sources[0]
			second.ID = "second"
			s.value.Sources = append(s.value.Sources, second)
			s.value.Models = append(s.value.Models, CatalogModel{ID: "second-route", Name: "Second", Protocol: second.Protocol, Strategy: "fixed", Candidates: []ModelCandidate{{second.ID, "second"}}})
			main := func(id string) {
				saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]string{"baseUrl": s.baseURL + "/v1"}, "main": map[string]string{"model": id}})
			}
			main("coding-main")
			view, _ := s.agents.View(context.Background(), kind)
			body, _ := json.Marshal(map[string]string{"kind": kind, "model": gatewayDefaultModel, "revision": view.Revision, "catalogRevision": s.value.Revision})
			w := httptest.NewRecorder()
			h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(body))))
			if w.Code != 200 {
				t.Fatalf("apply default: %d %s", w.Code, w.Body)
			}
			view, _ = s.agents.View(context.Background(), kind)
			if view.Current.Model != gatewayDefaultModel || !view.Profiles[0].Applied {
				t.Fatalf("wrong native default: %+v", view)
			}
			var native map[string]any
			switch kind {
			case "pi":
				raw, _ := os.ReadFile(filepath.Join(os.Getenv("PI_CODING_AGENT_DIR"), "models.json"))
				_ = json.Unmarshal(raw, &native)
				var provider map[string]any
				for _, row := range native["providers"].(map[string]any) {
					provider = row.(map[string]any)
				}
				if len(provider["models"].([]any)) != 3 {
					t.Fatal("Pi cannot select all routes and default")
				}
			case "opencode":
				raw, _ := os.ReadFile(os.Getenv("OPENCODE_CONFIG"))
				_ = json.Unmarshal(raw, &native)
				var provider map[string]any
				for _, row := range native["providers"].(map[string]any) {
					provider = row.(map[string]any)
				}
				if len(provider["models"].(map[string]any)) != 3 {
					t.Fatal("OpenCode cannot select all routes and default")
				}
			case "codex":
				raw, _ := os.ReadFile(filepath.Join(os.Getenv("CODEX_HOME"), "config.toml"))
				if !strings.Contains(string(raw), `"model_catalog_url" = "`+s.baseURL+`/v1/models"`) {
					t.Fatal("Codex remote model discovery is not enabled")
				}
			}
			catalogPath := "/v1/models"
			if kind == "codex" {
				catalogPath += "?client_version=0.167.2"
			}
			w = requestWithKey(h, s.credential(kind), catalogPath, "")
			var list struct {
				Models []struct{ Slug string }
				Data   []struct{ ID string }
			}
			if json.Unmarshal(w.Body.Bytes(), &list) != nil || w.Code != 200 || len(list.Models)+len(list.Data) != 3 {
				t.Fatalf("incomplete discovery: %d %s", w.Code, w.Body)
			}
			if w = keyAction(t, h, kind, "rotate"); w.Code != 200 {
				t.Fatalf("key rotation failed: %d %s", w.Code, w.Body)
			}
			view, _ = s.agents.View(context.Background(), kind)
			if (kind == "pi" || kind == "opencode") && len(view.Profiles[0].Models) != 3 {
				t.Fatal("key rotation lost the native model catalog")
			}
			path, payload := "/v1/chat/completions", `{"model":"roami-default","messages":[{"role":"user","content":"hi"}]}`
			if kind == "codex" {
				path, payload = "/v1/responses", `{"model":"roami-default","input":"hi"}`
			}
			if w = requestWithKey(h, s.credential(kind), path, payload); w.Code != 200 || got != "fixture" {
				t.Fatalf("default forwarding: %d %s", w.Code, w.Body)
			}
			main("second-route")
			if w = requestWithKey(h, s.credential(kind), path, payload); w.Code != 200 || got != "second" {
				t.Fatal("default did not follow main across sources")
			}
			if _, err := s.agents.Restore(context.Background(), kind, view.Revision); err != nil {
				t.Fatalf("restore failed: %v", err)
			}
		})
	}
}
