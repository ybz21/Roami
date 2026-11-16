package modelgateway

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/ybz21/Roami/internal/agentproviders"
)

func TestModelDirectoryEvidenceIsCachedScopedAndNeverInvented(t *testing.T) {
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		_, _ = w.Write([]byte(`{"data":[{"id":"vision","architecture":{"input_modalities":["text","image"]},"supported_parameters":["tools","structured_outputs"],"pricing":{"prompt":"0","completion":"0"}},{"id":"unknown"}]}`))
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	s := h.Catalog
	next := s.snapshot()
	next.Models[0].Candidates[0].Model = "vision"
	next.Models = append(next.Models, CatalogModel{ID: "pool", Name: "Pool", Protocol: "openai-completions", Aggregate: true, FreeOnly: true, Strategy: "order", Candidates: []ModelCandidate{{"work", "vision"}}})
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	query := func(path string) string {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", path, nil))
		if w.Code != 200 {
			t.Fatal(w.Code, w.Body.String())
		}
		return w.Body.String()
	}
	before := query("/v1/model-gateway/models")
	if hits.Load() != 0 || !strings.Contains(before, `"support":"unknown"`) {
		t.Fatal("list performed implicit discovery", before)
	}
	after := query("/v1/model-gateway/models?refresh=true&all=true")
	if hits.Load() != 1 || !strings.Contains(after, `"id":"unknown"`) || strings.Contains(after, "upstream-secret") || strings.Contains(after, `"evidence":"verified"`) {
		t.Fatal(after)
	}
	image := query("/v1/model-gateway/models?capability=image")
	if !strings.Contains(image, `"id":"coding-main"`) || strings.Contains(image, `"id":"pool"`) || hits.Load() != 1 {
		t.Fatal("aggregate union advertised as guaranteed", image)
	}
	free := query("/v1/model-gateway/models?free=true")
	if !strings.Contains(free, `"id":"pool"`) || strings.Contains(free, `"id":"coding-main"`) {
		t.Fatal("zero token price confused with free policy", free)
	}
	source := s.value.Sources[0]
	display := source
	display.Name = "Renamed"
	display.HasKey = !source.HasKey
	if sourceDirectoryFingerprint(source) != sourceDirectoryFingerprint(display) {
		t.Fatal("display fields invalidated capability evidence")
	}
	source.APIKey = "new-fixture-credential"
	s.rememberSourceDetails(source, s.value.Revision, []agentproviders.SourceModelDetail{{ID: "fake"}})
	if strings.Contains(query("/v1/model-gateway/models?all=true"), "fake") {
		t.Fatal("unsaved source poisoned cache")
	}
}
func TestSelectedNativeModelUsesFreeRoutesWithoutChangingDefaults(t *testing.T) {
	var paid, free atomic.Int32
	handler := func(counter *atomic.Int32) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			counter.Add(1)
			if r.Header.Get("X-Roami-Model-Selection") != "" || r.Header.Get("X-Roami-Free-Only") != "" {
				t.Error("selection headers escaped upstream")
			}
			_, _ = w.Write([]byte(`{"choices":[{"message":{"role":"assistant","content":"ok"}}],"usage":{"prompt_tokens":4,"completion_tokens":1}}`))
		}
	}
	a, b := httptest.NewServer(handler(&paid)), httptest.NewServer(handler(&free))
	defer a.Close()
	defer b.Close()
	h := catalogHandler(t, a.URL, "openai-completions")
	s := h.Catalog
	next := s.snapshot()
	next.Sources = append(next.Sources, ModelSource{ID: "free", Name: "Free", BaseURL: b.URL, Protocol: "openai-completions", AuthMode: "bearer"})
	next.Models = append(next.Models, CatalogModel{ID: "pool", Name: "Pool", Protocol: "openai-completions", Aggregate: true, Strategy: "order", Candidates: []ModelCandidate{{"work", "paid"}, {"free", "free"}}})
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	cfg := testConfiguration(nil)
	cfg.Pricing.Sources = map[string]SourcePricing{"work": {Default: PriceRule{Mode: "tokens", Price: ModelPricing{1, 1, 0}}}, "free": {Default: PriceRule{Mode: "free", Confirmed: true}}}
	if err := h.Ledger.Configure(cfg); err != nil {
		t.Fatal(err)
	}
	saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]any{"baseUrl": a.URL, "apiKey": "fixture"}, "main": map[string]any{"model": "default-main"}, "worker": map[string]any{"model": "default-worker"}})
	route, err := readNodeModels(h.Ledger.paths, "worker")
	if err != nil {
		t.Fatal(err)
	}
	call := func(revision, identity string) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		r := httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(`{"model":"pool","messages":[{"role":"user","content":"hello"}]}`))
		r.Header.Set("X-Roami-Model-Role", "worker")
		r.Header.Set("X-Roami-Model-Selection", "pool")
		r.Header.Set("X-Roami-Model-Revision", revision)
		r.Header.Set("X-Roami-Model-Route", identity)
		r.Header.Set("X-Roami-Free-Only", "true")
		h.ServeHTTP(w, r)
		return w
	}
	w := call(s.value.Revision, route.identity())
	if w.Code != 200 || paid.Load() != 0 || free.Load() != 1 {
		t.Fatal("free-only leaked into paid route", w.Code, w.Body.String(), paid.Load(), free.Load())
	}
	unchanged, _ := readNodeModels(h.Ledger.paths, "worker")
	if unchanged.model != "default-worker" {
		t.Fatal("global role changed")
	}
	if w := call("old", route.identity()); w.Code != 409 || free.Load() != 1 {
		t.Fatal("stale selection was forwarded", w.Code)
	}
	if w := call(s.value.Revision, ""); w.Code != 409 || free.Load() != 1 {
		t.Fatal("unbound selection was forwarded", w.Code)
	}
	cfg.Pricing.Sources["free"] = SourcePricing{Default: PriceRule{Mode: "unknown"}}
	if err := h.Ledger.Configure(cfg); err != nil {
		t.Fatal(err)
	}
	if w := call(s.value.Revision, route.identity()); w.Code != 503 || paid.Load() != 0 || free.Load() != 1 {
		t.Fatal("unknown pricing entered free route", w.Code, w.Body.String())
	}
}
func TestModelSelectionRejectsDisabledMissingAndIncompatibleModels(t *testing.T) {
	h := catalogHandler(t, "https://example.test/v1", "openai-completions")
	saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]any{"baseUrl": h.Catalog.baseURL + "/v1", "apiKey": "fixture"}, "main": map[string]any{"model": "coding-main"}, "worker": map[string]any{"model": "coding-main"}})
	for _, id := range []string{"auto", "coding-main", "missing"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/models/selection?role=main&model="+id, nil))
		if id == "missing" {
			if w.Code != 400 {
				t.Fatal(w.Code)
			}
			continue
		}
		var reply struct {
			Data struct {
				Model string `json:"model"`
			} `json:"data"`
		}
		_ = json.Unmarshal(w.Body.Bytes(), &reply)
		if w.Code != 200 || reply.Data.Model != "coding-main" {
			t.Fatal(w.Code, w.Body.String())
		}
	}
}

func TestFreeSelectionRejectsPricingChangesDuringAdmission(t *testing.T) {
	ledger := newLedger(t)
	config := testConfiguration(nil)
	config.Pricing.Sources = map[string]SourcePricing{"source": {Default: PriceRule{Mode: "free", Confirmed: true}}}
	if err := ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	revision := routingPriceRevision(config)
	config.Pricing.Sources["source"] = SourcePricing{Default: PriceRule{Mode: "tokens", Price: ModelPricing{1, 1, 0}}}
	if err := ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	_, err := ledger.Admit("worker", "model", "", "", CallAttribution{SourceID: "source", Free: true, PricingRevision: revision})
	if err == nil || err.Error() != "MODEL_GATEWAY_ROUTE_CHANGED" {
		t.Fatal("stale free decision admitted after pricing changed", err)
	}
}
