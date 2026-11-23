package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"github.com/ybz21/Roami/internal/agentproviders"
	"github.com/ybz21/Roami/internal/modelgateway/directory"
	"github.com/ybz21/Roami/internal/modelgateway/hostroute"
)

func TestModelDirectoryEvidenceIsCachedScopedAndNeverInvented(t *testing.T) {
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		_, _ = w.Write([]byte(`{"data":[{"id":"vision","architecture":{"input_modalities":["text","image"],"output_modalities":["text"]},"supported_parameters":["tools","structured_outputs"],"pricing":{"prompt":"0","completion":"0"}},{"id":"unknown"},{"id":"paid-claude","architecture":{"input_modalities":["text","image"],"output_modalities":["text"]},"pricing":{"prompt":"0.001","completion":"0.002"}}]}`))
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
	var directory struct {
		Data struct {
			Models []directory.Row `json:"models"`
		} `json:"data"`
	}
	if err := json.Unmarshal([]byte(after), &directory); err != nil {
		t.Fatal(err)
	}
	if directory.Data.Models[0].Kind != "aggregate" {
		t.Fatal("aggregates must be first", after)
	}
	for _, row := range directory.Data.Models {
		if row.ID == "paid-claude" && (row.Pricing != "metered" || row.Configured || len(row.InputModalities) != 2 || len(row.OutputModalities) != 1) {
			t.Fatal("paid upstream pricing or modalities lost", row)
		}
		if row.ID == "coding-main" && (len(row.InputModalities) != 2 || len(row.OutputModalities) != 1) {
			t.Fatal("configured route lost input/output metadata", row)
		}
	}

	image := query("/v1/model-gateway/models?capability=image")
	if !strings.Contains(image, `"id":"coding-main"`) || strings.Contains(image, `"id":"pool"`) || hits.Load() != 1 {
		t.Fatal("aggregate union advertised as guaranteed", image)
	}
	free := query("/v1/model-gateway/models?free=true")
	if strings.Contains(free, `"id":"pool"`) || strings.Contains(free, `"id":"coding-main"`) {
		t.Fatal("zero advertised price or legacy policy mistaken for confirmed free", free)
	}
	cfg := testConfiguration(nil)
	cfg.Pricing.Sources = map[string]SourcePricing{"work": {Default: PriceRule{Mode: "free", Confirmed: true}}}
	if err := h.state.accounting.Configure(cfg); err != nil {
		t.Fatal(err)
	}
	if free := query("/v1/model-gateway/models?free=true"); !strings.Contains(free, `"id":"pool"`) || !strings.Contains(free, `"id":"coding-main"`) {
		t.Fatal("confirmed free routes missing", free)
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
			var payload map[string]any
			_ = json.NewDecoder(r.Body).Decode(&payload)
			if _, present := payload["roami_free_only"]; present {
				t.Error("local free-only option escaped upstream")
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
	next.Models = append(next.Models, CatalogModel{ID: "pool", Name: "Pool", Protocol: "openai-completions", Aggregate: true, FreeOnly: true, Strategy: "order", Candidates: []ModelCandidate{{"work", "paid"}, {"free", "free"}}})
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	cfg := testConfiguration(nil)
	cfg.Pricing.Sources = map[string]SourcePricing{"work": {Default: PriceRule{Mode: "tokens", Price: ModelPricing{1, 1, 0}}}, "free": {Default: PriceRule{Mode: "free", Confirmed: true}}}
	if err := h.state.accounting.Configure(cfg); err != nil {
		t.Fatal(err)
	}
	saveNodeModels(t, h.state, map[string]any{"connection": map[string]any{"baseUrl": a.URL, "apiKey": "fixture"}, "main": map[string]any{"model": "default-main"}, "worker": map[string]any{"model": "default-worker"}})
	route, err := hostroute.Read(h.state.paths, "worker")
	if err != nil {
		t.Fatal(err)
	}
	call := func(identity string, freeOnly bool) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		body := `{"model":"pool","messages":[{"role":"user","content":"hello"}]}`
		if freeOnly {
			body = `{"roami_free_only":true,` + body[1:]
		}
		r := httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(body))
		r.Header.Set("X-Roami-Model-Role", "worker")
		r.Header.Set("X-Roami-Model-Route", identity)
		h.ServeHTTP(w, r)
		return w
	}
	w := call(route.Identity(), true)
	if w.Code != 200 || paid.Load() != 0 || free.Load() != 1 {
		t.Fatal("free-only leaked into paid route", w.Code, w.Body.String(), paid.Load(), free.Load())
	}
	unchanged, _ := hostroute.Read(h.state.paths, "worker")
	if unchanged.Model != "default-worker" {
		t.Fatal("global role changed")
	}
	if w := call("stale-route", true); w.Code != 409 || free.Load() != 1 {
		t.Fatal("stale role settings were forwarded", w.Code)
	}
	cfg.Pricing.Sources["free"] = SourcePricing{Default: PriceRule{Mode: "unknown"}}
	if err := h.state.accounting.Configure(cfg); err != nil {
		t.Fatal(err)
	}
	if w := call(route.Identity(), true); w.Code != 503 || paid.Load() != 0 || free.Load() != 1 {
		t.Fatal("unknown pricing entered free route", w.Code, w.Body.String())
	}
	if w := call(route.Identity(), false); w.Code != 200 || paid.Load() != 1 || free.Load() != 1 {
		t.Fatal("legacy member filter blocked the saved paid member", w.Code, w.Body.String())
	}
	h.Catalog = nil
	if w := call(route.Identity(), true); w.Code != 503 || paid.Load() != 1 {
		t.Fatal("free-only bypassed the unavailable catalog", w.Code, w.Body.String())
	}
}
func TestNativeModelRejectsMissingAndDisabledRoutes(t *testing.T) {
	h := catalogHandler(t, "https://example.test/v1", "openai-completions")
	saveNodeModels(t, h.state, map[string]any{"connection": map[string]any{"baseUrl": h.Catalog.baseURL + "/v1", "apiKey": "fixture"}, "main": map[string]any{"model": "coding-main"}})
	for _, id := range []string{"missing", "coding-main"} {
		if id == "coding-main" {
			key := h.Catalog.value.AgentKeys["roami"]
			key.Disabled = true
			h.Catalog.value.AgentKeys["roami"] = key
		}
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(`{"model":"`+id+`"}`)))
		if id == "missing" && w.Code != 400 || id == "coding-main" && w.Code != 403 {
			t.Fatal(id, w.Code, w.Body.String())
		}
	}
}

func TestFreeSelectionRejectsPricingChangesDuringAdmission(t *testing.T) {
	ledger := newLedger(t)
	config := testConfiguration(nil)
	config.Pricing.Sources = map[string]SourcePricing{"source": {Default: PriceRule{Mode: "free", Confirmed: true}}}
	if err := ledger.accounting.Configure(config); err != nil {
		t.Fatal(err)
	}
	revision := routingPriceRevision(config)
	config.Pricing.Sources["source"] = SourcePricing{Default: PriceRule{Mode: "tokens", Price: ModelPricing{1, 1, 0}}}
	if err := ledger.accounting.Configure(config); err != nil {
		t.Fatal(err)
	}
	_, err := ledger.accounting.Admit("worker", "model", "", "", CallAttribution{SourceID: "source", Free: true, PricingRevision: revision})
	if err == nil || err.Error() != "MODEL_GATEWAY_ROUTE_CHANGED" {
		t.Fatal("stale free decision admitted after pricing changed", err)
	}
}

func TestDirectoryPreservesInputOutputEvidenceAndAggregatePriority(t *testing.T) {
	h := catalogHandler(t, "https://example.test/v1", "openai-completions")
	s := h.Catalog
	next := s.snapshot()
	next.Models[0].Candidates[0].Model = "vision"
	next.Models = append(next.Models, CatalogModel{ID: "z-pool", Name: "Pool", Protocol: "openai-completions", Aggregate: true, Strategy: "order", Candidates: []ModelCandidate{{"work", "vision"}}})
	if err := s.update(context.Background(), next); err != nil {
		t.Fatal(err)
	}
	s.rememberSourceDetails(s.value.Sources[0], s.value.Revision, []agentproviders.SourceModelDetail{
		{ID: "vision", InputModalities: []string{"text", "image"}, OutputModalities: []string{"text"}, Context: 64000, Output: 8000},
		{ID: "upstream", InputModalities: []string{"audio"}, OutputModalities: []string{"text"}, Context: 32000, Output: 4000},
	})
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/models?all=true", nil))
	var result struct {
		Data struct {
			Models []directory.Row `json:"models"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	rows := result.Data.Models
	if len(rows) != 3 || rows[0].ID != "z-pool" || rows[0].InputModalities != nil || rows[0].OutputModalities != nil {
		t.Fatal("aggregate order or unsupported union", rows)
	}
	if rows[1].ID != "coding-main" || strings.Join(rows[1].InputModalities, ",") != "text,image" || strings.Join(rows[1].OutputModalities, ",") != "text" || rows[1].ContextWindow != 64000 || rows[1].MaxOutputTokens != 8000 {
		t.Fatal("configured evidence lost", rows[1])
	}
	if rows[2].Configured || strings.Join(rows[2].InputModalities, ",") != "audio" || rows[2].MaxOutputTokens != 4000 {
		t.Fatal("upstream evidence lost", rows[2])
	}
}
