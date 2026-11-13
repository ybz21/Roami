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

func TestClaudeDiscoveryAndDefaultFollowSavedMainAcrossSources(t *testing.T) {
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
	second.ID, second.Name = "other", "Other"
	s.value.Sources = append(s.value.Sources, second)
	s.value.Models = append(s.value.Models, CatalogModel{ID: "another-model", Name: "Another", Protocol: second.Protocol, Strategy: "fixed", Candidates: []ModelCandidate{{second.ID, "second"}}})
	main := func(id string) {
		saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]string{"baseUrl": s.baseURL + "/v1", "apiKey": s.credential("roami")}, "main": map[string]string{"model": id}})
	}
	main("coding-main")
	view, _ := s.agents.View(context.Background(), "claude")
	body, _ := json.Marshal(map[string]string{"kind": "claude", "model": gatewayDefaultModel, "revision": view.Revision, "catalogRevision": s.value.Revision})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/catalog/apply", strings.NewReader(string(body))))
	if w.Code != 200 || s.view(context.Background()).DefaultModel != "coding-main" {
		t.Fatalf("default apply failed: %d %s", w.Code, w.Body)
	}
	raw, _ := os.ReadFile(filepath.Join(os.Getenv("CLAUDE_CONFIG_DIR"), "settings.json"))
	var settings struct {
		Model string
		Env   map[string]string
	}
	_ = json.Unmarshal(raw, &settings)
	if settings.Model != gatewayDefaultModel || settings.Env["ANTHROPIC_DEFAULT_MODEL"] != gatewayDefaultModel || settings.Env["ANTHROPIC_MODEL"] != "" || settings.Env["ANTHROPIC_DEFAULT_FABLE_MODEL"] != gatewayDefaultModel {
		t.Fatal("default selection is pinned or aliases escape the gateway")
	}
	request := func(kind, method, path, body string) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		r := httptest.NewRequest(method, path, strings.NewReader(body))
		r.Header.Set("Authorization", "Bearer "+s.credential(kind))
		h.publicModels(w, r)
		return w
	}
	listed := request("claude", "GET", "/v1/models?limit=1000", "")
	var list struct{ Data []struct{ ID string } }
	_ = json.Unmarshal(listed.Body.Bytes(), &list)
	if listed.Code != 200 || len(list.Data) != 2 {
		t.Fatalf("missing gateway models: %s", listed.Body)
	}
	for _, row := range list.Data {
		if !strings.HasPrefix(row.ID, claudeModelPrefix) {
			t.Fatalf("Claude filters %s from discovery", row.ID)
		}
	}
	payload := func(id string) string {
		return `{"model":"` + id + `","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}`
	}
	for _, id := range []string{gatewayDefaultModel, gatewayDefaultModel + "[1m]", claudeModelPrefix + "another-model", claudeModelPrefix + "another-model[1m]", "coding-main"} {
		got = ""
		w := request("claude", "POST", "/v1/messages", payload(id))
		want := "fixture"
		if strings.Contains(id, "another-model") {
			want = "second"
		}
		if w.Code != 200 || got != want || !strings.Contains(w.Body.String(), `"model":"`+id+`"`) {
			t.Fatalf("route %s: %d %s upstream=%s", id, w.Code, w.Body, got)
		}
	}
	main("another-model")
	if w := request("claude", "POST", "/v1/messages", payload(gatewayDefaultModel)); w.Code != 200 || got != "second" {
		t.Fatalf("default did not follow changed main: %d %s", w.Code, w.Body)
	}
	if uses := s.uses(context.Background()); !containsField(uses["another-model"], "claude") {
		t.Fatal("default target is not protected from deletion")
	}
	main("missing")
	got = ""
	if w := request("claude", "POST", "/v1/messages", payload(gatewayDefaultModel)); w.Code != 400 || got != "" {
		t.Fatal("missing default silently chose another model")
	}
	if w := request("codex", "GET", "/v1/models", ""); strings.Contains(w.Body.String(), claudeModelPrefix) {
		t.Fatal("Claude discovery aliases leaked into other clients")
	}
}

func TestClaudeDefaultMatchesOnlyTheSavedDirectSource(t *testing.T) {
	h := catalogHandler(t, "https://upstream.example/v1", "openai-completions")
	saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]string{"baseUrl": "https://upstream.example/v1", "apiKey": "upstream-secret"}, "main": map[string]string{"model": "fixture"}})
	if model := h.Catalog.defaultModel(h.Catalog.value); model == nil || model.ID != "coding-main" {
		t.Fatal("saved direct main cannot use its existing gateway route")
	}
	saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]string{"baseUrl": "https://other.example/v1", "apiKey": "upstream-secret"}, "main": map[string]string{"model": "fixture"}})
	if model := h.Catalog.defaultModel(h.Catalog.value); model != nil {
		t.Fatal("same model name matched a different source")
	}
}
