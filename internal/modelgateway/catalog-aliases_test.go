package modelgateway

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestAggregateRenameKeepsBoundCallsAndNestedReferences(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.WriteString(w, `{"id":"ok","choices":[{"message":{"content":"ok"}}],"usage":{"prompt_tokens":1,"completion_tokens":1}}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	s := h.Catalog
	v := s.snapshot()
	v.Models = append(v.Models, CatalogModel{ID: "old", Name: "Pool", Aggregate: true, Protocol: "openai-completions", Strategy: "order", Candidates: []ModelCandidate{{"work", "fixture"}}}, CatalogModel{ID: "parent", Name: "Parent", Aggregate: true, Protocol: "openai-completions", Strategy: "order", Candidates: []ModelCandidate{{groupSource, "old"}}})
	if err := s.update(context.Background(), v); err != nil {
		t.Fatal(err)
	}
	saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]string{"baseUrl": s.baseURL + "/v1", "apiKey": s.credential("roami")}, "main": map[string]string{"model": "old"}, "worker": map[string]string{"model": "old"}})
	v = s.snapshot()
	v.Models[1].ID = "new"
	v.Models[1].Aliases = []string{"old"}
	if err := s.update(context.Background(), v); err != nil {
		t.Fatal(err)
	}
	if s.value.Models[2].Candidates[0].Model != "new" {
		t.Fatal("nested reference not updated")
	}
	view := s.view(context.Background())
	if len(view.Uses["new"]) == 0 || len(view.Uses["old"]) != 0 || view.DefaultModel != "new" {
		t.Fatal("binding identity or default lost")
	}
	reopened, err := openCatalog(h.Ledger)
	if err != nil || findCatalogModel(reopened.value.Models, "old") == nil {
		t.Fatal("rename not persisted", err)
	}
	for _, id := range []string{"old", "new", "parent"} {
		request := httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(fmt.Sprintf(`{"model":%q,"messages":[{"role":"user","content":"test"}]}`, id)))
		w := httptest.NewRecorder()
		h.forwardCatalog(w, request, s.snapshot(), "roami", "openai-completions")
		if w.Code != 200 {
			t.Fatalf("%s: %d %s", id, w.Code, w.Body.String())
		}
	}
	v = s.snapshot()
	v.Models = v.Models[:1]
	if err := s.update(context.Background(), v); err == nil || err.Error() != "MODEL_CATALOG_IN_USE" {
		t.Fatalf("deleted bound alias: %v", err)
	}
}

func TestAggregateAliasValidationAndMemberBounds(t *testing.T) {
	old := CatalogModel{ID: "old", Aggregate: true, Protocol: "openai-completions"}
	for _, aliases := range [][]string{{"invented"}, {"old", "old"}, {gatewayDefaultModel}, {"other"}} {
		next := old
		next.ID = "new"
		next.Aliases = aliases
		if validateModelAliases([]CatalogModel{old, {ID: "other"}}, []CatalogModel{next}) == nil {
			t.Fatalf("invalid aliases accepted: %v", aliases)
		}
	}
	h := catalogHandler(t, "https://provider.example/v1", "openai-completions")
	for _, count := range []int{9, 64, 65} {
		v := h.Catalog.snapshot()
		m := CatalogModel{ID: "pool", Name: "Pool", Aggregate: true, Protocol: "openai-completions", Strategy: "weight", Weights: map[string]int{}}
		for i := 0; i < count; i++ {
			c := ModelCandidate{"work", fmt.Sprintf("m%d", i)}
			m.Candidates = append(m.Candidates, c)
			m.Weights[candidateIdentity(c)] = 1
		}
		v.Models = append(v.Models[:1], m)
		err := h.Catalog.update(context.Background(), v)
		if (err == nil) != (count <= 64) {
			t.Fatalf("%d members: %v", count, err)
		}
	}
	v := h.Catalog.snapshot()
	v.Models = v.Models[:1]
	v.Models[0].Strategy = "failover"
	v.Models[0].Candidates = nil
	for i := 0; i < 9; i++ {
		v.Models[0].Candidates = append(v.Models[0].Candidates, ModelCandidate{"work", fmt.Sprint(i)})
	}
	if h.Catalog.update(context.Background(), v) == nil {
		t.Fatal("native failover limit changed")
	}
}

func TestAggregateManualOrderDoesNotChangeEntryProtocol(t *testing.T) {
	h := catalogHandler(t, "https://provider.example/v1", "openai-completions")
	v := h.Catalog.snapshot()
	v.Sources = append(v.Sources, ModelSource{ID: "anthropic", Name: "Anthropic", BaseURL: "https://anthropic.example/v1", Protocol: "anthropic-messages", AuthMode: "api_key"})
	v.Models = append(v.Models, CatalogModel{ID: "ordered", Name: "Ordered", Aggregate: true, Protocol: "openai-completions", Strategy: "order", Candidates: []ModelCandidate{{"work", "a"}, {"anthropic", "b"}}})
	if err := h.Catalog.update(context.Background(), v); err != nil {
		t.Fatal(err)
	}
	v = h.Catalog.snapshot()
	v.Models[1].Candidates = []ModelCandidate{{"anthropic", "b"}, {"work", "a"}}
	if err := h.Catalog.update(context.Background(), v); err != nil {
		t.Fatal("reordering incompatible source protocols should not redefine the entry protocol:", err)
	}
	if h.Catalog.value.Models[1].Protocol != "openai-completions" {
		t.Fatal("entry protocol changed")
	}
}

func TestDirectModelNameDoesNotResolveAsGatewayAlias(t *testing.T) {
	h := catalogHandler(t, "https://provider.example/v1", "openai-completions")
	v := h.Catalog.snapshot()
	v.Models = append(v.Models, CatalogModel{ID: "old", Name: "Pool", Aggregate: true, Protocol: "openai-completions", Strategy: "order", Candidates: []ModelCandidate{{"work", "fixture"}}})
	if err := h.Catalog.update(context.Background(), v); err != nil {
		t.Fatal(err)
	}
	v = h.Catalog.snapshot()
	v.Models[1].ID = "new"
	v.Models[1].Aliases = []string{"old"}
	if err := h.Catalog.update(context.Background(), v); err != nil {
		t.Fatal(err)
	}
	saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]string{"baseUrl": "https://provider.example/v1", "apiKey": "upstream-secret"}, "main": map[string]string{"model": "old"}, "worker": map[string]string{"model": "old"}})
	if h.Catalog.view(context.Background()).RoamiModels["main"] != "old" {
		t.Fatal("direct upstream model name was treated as a gateway alias")
	}
}
