package modelgateway

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPoolHidesDirectGatewayMembersAndPublishesAlias(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(responseFixture))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL+"/v1", "openai-responses")
	ctx := context.Background()
	next := h.Catalog.snapshot()
	direct := &next.Models[0]
	direct.Aliases = []string{direct.ID}
	direct.ID, direct.GatewayAlias = "direct", "blade-direct"
	next.Models = append(next.Models,
		CatalogModel{ID: "nested", Name: "Nested", Aggregate: true, Strategy: "order", Protocol: direct.Protocol, Candidates: direct.Candidates},
		CatalogModel{ID: "pool", Name: "Pool", Aggregate: true, Strategy: "order", Protocol: direct.Protocol, GatewayAlias: "blade-pool", HideMembers: true, Candidates: []ModelCandidate{{groupSource, "nested"}}},
	)
	if err := h.Catalog.update(ctx, next); err != nil {
		t.Fatal(err)
	}
	read := func(path string, public bool) string {
		t.Helper()
		req := httptest.NewRequest(http.MethodGet, path, nil)
		req.Header.Set("Authorization", "Bearer "+h.Catalog.credential("codex"))
		w := httptest.NewRecorder()
		if public {
			h.publicModels(w, req)
		} else {
			h.ServeHTTP(w, req)
		}
		if w.Code != http.StatusOK {
			t.Fatalf("directory %s: %d %s", path, w.Code, w.Body)
		}
		return w.Body.String()
	}
	for _, route := range []string{"/v1/models", "/v1/models?client_version=1"} {
		list := read(route, true)
		if !strings.Contains(list, "blade-pool") || !strings.Contains(list, "nested") || strings.Contains(list, "direct") {
			t.Fatalf("unexpected published directory: %s", list)
		}
	}
	if list := read("/v1/model-gateway/models?all=true", false); strings.Contains(list, `"id":"direct"`) || !strings.Contains(list, "blade-pool") {
		t.Fatalf("unexpected management directory: %s", list)
	}
	if list := read("/v1/model-gateway/models?includeHidden=true", false); !strings.Contains(list, `"gatewayHidden":true`) || !strings.Contains(list, `"id":"direct"`) {
		t.Fatalf("aggregation editor cannot read the hidden member: %s", list)
	}
	call := func(id string) *httptest.ResponseRecorder {
		return catalogRequest(h, "/v1/responses", fmt.Sprintf(`{"model":%q,"input":"hello"}`, id))
	}
	for _, id := range []string{"direct", "blade-direct", "coding-main"} {
		if w := call(id); w.Code != http.StatusBadRequest || !strings.Contains(w.Body.String(), "MODEL_NOT_CONFIGURED") {
			t.Fatalf("hidden route %s: %d %s", id, w.Code, w.Body)
		}
	}
	for _, id := range []string{"pool", "blade-pool"} {
		if w := call(id); w.Code != http.StatusOK {
			t.Fatalf("pool %s: %d %s", id, w.Code, w.Body)
		}
	}
	next = h.Catalog.snapshot()
	next.Models[2].HideMembers = false
	if err := h.Catalog.update(ctx, next); err != nil {
		t.Fatal(err)
	}
	if w := call("blade-direct"); w.Code != http.StatusOK {
		t.Fatalf("restored direct route: %d %s", w.Code, w.Body)
	}
}

func TestGatewayAliasCannotCollideWithModelNames(t *testing.T) {
	h := catalogHandler(t, "https://models.example/v1", "openai-responses")
	next := h.Catalog.snapshot()
	for _, invalid := range []string{"coding-main", "roami-default", "name with spaces"} {
		next.Models[0].GatewayAlias = invalid
		if err := h.Catalog.update(context.Background(), next); err == nil || err.Error() != "INVALID_MODEL_GATEWAY_ALIAS" {
			t.Fatalf("invalid alias %q: %v", invalid, err)
		}
	}
}
