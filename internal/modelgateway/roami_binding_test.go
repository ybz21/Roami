package modelgateway

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestRoamiSingleRoleBindingPreservesOtherRole(t *testing.T) {
	for _, role := range []string{"main", "worker"} {
		for _, gateway := range []bool{false, true} {
			t.Run(role+map[bool]string{false: "/direct", true: "/gateway"}[gateway], func(t *testing.T) {
				h := catalogHandler(t, "https://provider.example/v1", "openai-completions")
				s := h.Catalog
				next := s.snapshot()
				next.Models = append(next.Models, CatalogModel{ID: "workbuddy-hy4", Name: "WorkBuddy Hy4", Protocol: "openai-completions", Strategy: "fixed", Candidates: []ModelCandidate{{"work", "hy4-preview-f"}}})
				if err := s.update(context.Background(), next); err != nil {
					t.Fatal(err)
				}
				other := "worker"
				if role == "worker" {
					other = "main"
				}
				endpoint, model, key := "https://provider.example/v1", "fixture", "upstream-secret"
				if gateway {
					endpoint, model, key = s.baseURL+"/v1", "coding-main", s.credential("roami")
				}
				before := map[string]any{"connection": map[string]any{"baseUrl": endpoint, "apiKey": key}, "main": map[string]any{"model": model}, "worker": map[string]any{"model": model}}
				saveNodeModels(t, h.Ledger, before)
				preserved := map[string]any{"model": "coding-main", "images": true, "contextWindow": float64(64000), "reasoningEffort": "high"}
				root, err := os.MkdirTemp("", "roami-single-role-")
				if err != nil {
					t.Fatal(err)
				}
				defer os.RemoveAll(root)
				s.agentSocket = filepath.Join(root, "agent.sock")
				listener, err := net.Listen("unix", s.agentSocket)
				if err != nil {
					t.Fatal(err)
				}
				writes := make(chan map[string]any, 1)
				server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if r.Method == "PUT" {
						var written map[string]any
						_ = json.NewDecoder(r.Body).Decode(&written)
						saveNodeModels(t, h.Ledger, written)
						writes <- written
					}
					writeJSON(w, 200, map[string]any{"data": map[string]any{
						role: map[string]any{"model": model, "images": false}, other: map[string]any{"model": model, "images": true, "configuredContextWindow": 64000, "reasoningEffort": "high"},
					}})
				})}
				go server.Serve(listener)
				defer server.Close()
				apply := func(revision string) *httptest.ResponseRecorder {
					body, _ := json.Marshal(map[string]any{"role": role, "model": "workbuddy-hy4", "revision": revision})
					w := httptest.NewRecorder()
					h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/roles", strings.NewReader(string(body))))
					return w
				}
				if w := apply("stale"); w.Code != 409 || len(writes) != 0 {
					t.Fatal("stale selection changed runtime settings")
				}
				if w := apply(s.value.Revision); w.Code != 200 {
					t.Fatalf("binding failed: %d %s", w.Code, w.Body.String())
				}
				written := <-writes
				if !reflect.DeepEqual(written[other], preserved) {
					t.Fatalf("other role changed: %#v", written[other])
				}
				if got := written[role].(map[string]any); got["model"] != "workbuddy-hy4" || got["reasoningEffort"] != nil || got["contextWindow"] != nil {
					t.Fatalf("selected role was not reset: %#v", got)
				}
				route, err := readNodeModels(h.Ledger.paths, role)
				if err != nil || route.endpoint != s.baseURL+"/v1" || route.key != s.credential("roami") || route.model != "workbuddy-hy4" {
					t.Fatalf("incorrect gateway connection: %+v %v", route, err)
				}
				if s.value.RolesBackup == nil {
					t.Fatal("missing restore point")
				}
				saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]string{"baseUrl": "https://unmapped.example/v1", "apiKey": "other-key"}, "main": map[string]string{"model": "fixture"}, "worker": map[string]string{"model": "fixture"}})
				if w := apply(s.value.Revision); w.Code != 409 || !strings.Contains(w.Body.String(), "MODEL_ROLE_REQUIRES_BINDING") || len(writes) != 0 {
					t.Fatalf("unmapped role was overwritten: %d %s", w.Code, w.Body.String())
				}
			})
		}
	}
}
