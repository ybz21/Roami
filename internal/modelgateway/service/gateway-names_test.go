package service

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
)

func TestGatewayPublishesAndRoutesSourceQualifiedModelIDs(t *testing.T) {
	const upstreamModel = "vendor/model:free"
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		var request struct{ Model string }
		if err := json.NewDecoder(r.Body).Decode(&request); err != nil || request.Model != upstreamModel {
			t.Errorf("upstream received the wrong model: %q (%v)", request.Model, err)
		}
		fmt.Fprintf(w, `{"choices":[{"message":{"role":"assistant","content":%q}}]}`, r.URL.Path)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL+"/first/v1", "openai-completions")
	s := h.Catalog
	next := s.snapshot()
	firstKey, secondKey := "Blade-01", "Backup"
	next.Sources[0].SourceKey = &firstKey
	second := next.Sources[0]
	second.ID, second.BaseURL, second.SourceKey = "second", upstream.URL+"/second/v1", &secondKey
	next.Sources = append(next.Sources, second)
	next.Models[0].Candidates[0].Model = upstreamModel
	other := next.Models[0]
	other.ID, other.Candidates = "other-route", []ModelCandidate{{second.ID, upstreamModel}}
	duplicate := next.Models[0]
	duplicate.ID = "duplicate-route"
	pool := CatalogModel{ID: "pool", Name: "Pool", Aggregate: true, Strategy: "order", Protocol: other.Protocol, Candidates: other.Candidates}
	next.Models = append(next.Models, other, duplicate, pool)
	ctx := context.Background()
	if err := s.update(ctx, next); err != nil {
		t.Fatal(err)
	}
	firstID, secondID := firstKey+"/"+upstreamModel, secondKey+"/"+upstreamModel
	if got := s.view(ctx).QualifiedModelIDs; !maps.Equal(got, map[string]string{"coding-main": firstID, other.ID: secondID}) {
		t.Fatalf("wrong management model IDs: %v", got)
	}
	list := func(path, kind string, want []string) {
		t.Helper()
		w := requestWithKey(h, s.credential(kind), path, "")
		var catalog struct {
			Data   []struct{ ID string }
			Models []struct{ Slug string }
		}
		if err := json.Unmarshal(w.Body.Bytes(), &catalog); err != nil || w.Code != http.StatusOK {
			t.Fatalf("list models: %d %s", w.Code, w.Body)
		}
		var got []string
		for _, row := range catalog.Data {
			got = append(got, row.ID)
		}
		for _, row := range catalog.Models {
			got = append(got, row.Slug)
		}
		if !slices.Equal(got, want) {
			t.Fatalf("%s discovery: got %v, want %v", kind, got, want)
		}
	}
	list("/v1/models", "roami", []string{firstID, secondID, duplicate.ID, pool.ID})
	list("/v1/models?client_version=1", "codex", []string{firstID, secondID, duplicate.ID, pool.ID})
	list("/v1/models", "claude", []string{claudeModelPrefix + firstID, claudeModelPrefix + secondID, claudeModelPrefix + duplicate.ID, claudeModelPrefix + pool.ID})
	call := func(name, wantPath string) {
		t.Helper()
		body := fmt.Sprintf(`{"model":%q,"messages":[{"role":"user","content":"hi"}]}`, name)
		w := requestWithKey(h, s.credential("roami"), "/v1/chat/completions", body)
		if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), wantPath+"/v1/chat/completions") {
			t.Fatalf("call %s: %d %s", name, w.Code, w.Body)
		}
	}
	call(firstID, "/first")
	call(secondID, "/second")
	call("coding-main", "/first")

	next = s.snapshot()
	next.Models[1].GatewayAlias = "backup-alias"
	if err := s.update(ctx, next); err != nil {
		t.Fatal(err)
	}
	list("/v1/models", "roami", []string{firstID, "backup-alias", duplicate.ID, pool.ID})
	call("backup-alias", "/second")
	call(secondID, "/second")

	saveNodeModels(t, h.state, map[string]any{"connection": map[string]string{"baseUrl": s.baseURL + "/v1"}, "main": map[string]string{"model": firstID}})
	if view := s.view(ctx); view.DefaultModel != "coding-main" || view.RoamiModels["main"] != "coding-main" || len(view.Uses["coding-main"]) != 1 {
		t.Fatalf("qualified binding did not resolve to the saved route: %+v", view.Uses)
	}
	next = s.snapshot()
	renamed := "renamed"
	next.Sources[0].SourceKey = &renamed
	if err := s.update(ctx, next); err == nil || err.Error() != "MODEL_CATALOG_IN_USE" {
		t.Fatalf("renamed a source key in use: %v", err)
	}
	call(firstID, "/first")
}
