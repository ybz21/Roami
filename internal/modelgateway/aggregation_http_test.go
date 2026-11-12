package modelgateway

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func aggregateFixture(t *testing.T, first, second http.HandlerFunc) *Handler {
	t.Helper()
	a, b := httptest.NewServer(first), httptest.NewServer(second)
	t.Cleanup(a.Close)
	t.Cleanup(b.Close)
	h := catalogHandler(t, a.URL, "openai-responses")
	value := h.Catalog.snapshot()
	value.Sources = append(value.Sources, ModelSource{ID: "backup", Name: "Backup", BaseURL: b.URL, Protocol: "openai-responses", AuthMode: "bearer"})
	value.Models[0].Aggregate = true
	value.Models[0].FreeOnly = true
	value.Models[0].Strategy = "smart"
	value.Models[0].Candidates = append(value.Models[0].Candidates, ModelCandidate{"backup", "fixture"})
	if err := h.Catalog.update(context.Background(), value); err != nil {
		t.Fatal(err)
	}
	config := testConfiguration(nil)
	config.Pricing.Sources = map[string]SourcePricing{"work": {Default: PriceRule{Mode: "free", Confirmed: true}}, "backup": {Default: PriceRule{Mode: "free", Confirmed: true}}}
	if err := h.Ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	monitor, err := openMonitorStore(filepath.Join(t.TempDir(), "monitor.ring"), 100, h.Ledger.now)
	if err != nil {
		t.Fatal(err)
	}
	h.Monitor = monitor
	t.Cleanup(func() { _ = monitor.Close() })
	return h
}
func responseFixture(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"id":"r","object":"response","status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"2"}]}],"usage":{"input_tokens":4,"output_tokens":1}}`))
}
func TestAggregateRetriesRejectedSourceHonorsCooldownAndKeepsAttempts(t *testing.T) {
	var first, second atomic.Int64
	h := aggregateFixture(t, func(w http.ResponseWriter, r *http.Request) {
		first.Add(1)
		w.Header().Set("Retry-After", "120")
		http.Error(w, `{"error":{"code":"rate_limit"}}`, 429)
	}, func(w http.ResponseWriter, r *http.Request) { second.Add(1); responseFixture(w, r) })
	for i := 0; i < 2; i++ {
		w := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello"}`)
		if w.Code != 200 {
			t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
		}
	}
	if first.Load() != 1 || second.Load() != 2 {
		t.Fatalf("cooldown not honored: %d %d", first.Load(), second.Load())
	}
	h.routing.mu.Lock()
	rest := h.routing.channels["work/fixture/"].RestUntil
	h.routing.mu.Unlock()
	if rest.Sub(h.Ledger.now()) < 110*time.Second {
		t.Fatal("ignored Retry-After")
	}
	rows, _, err := h.Monitor.Snapshot()
	if err != nil || len(rows) != 3 || rows[0].Success || !rows[1].Success {
		t.Fatalf("attempt monitoring: %+v %v", rows, err)
	}
	var count int
	if err = h.Ledger.db.QueryRow(`SELECT count(*) FROM gateway_calls`).Scan(&count); err != nil || count != 3 {
		t.Fatal("attempts were not independently accounted")
	}
}
func TestAggregateNeverReplaysAfterStreamStartsAndRejectsPaidZeroPrice(t *testing.T) {
	var backup atomic.Int64
	h := aggregateFixture(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("data: {\"type\":\"response.output_text.delta\",\"delta\":\"partial\"}\n\n"))
		w.(http.Flusher).Flush()
	}, func(w http.ResponseWriter, r *http.Request) { backup.Add(1); responseFixture(w, r) })
	w := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello","stream":true}`)
	if !strings.Contains(w.Body.String(), "partial") || backup.Load() != 0 {
		t.Fatal("replayed after output")
	}
	rows, _, _ := h.Monitor.Snapshot()
	if len(rows) != 1 || rows[0].Success {
		t.Fatal("incomplete stream counted as available")
	}
	config, _ := h.Ledger.Configuration()
	config.Pricing.Sources = map[string]SourcePricing{"work": {Default: PriceRule{Mode: "tokens"}}, "backup": {Default: PriceRule{Mode: "unknown"}}}
	if err := h.Ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	w = catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello"}`)
	if w.Code != 503 || backup.Load() != 0 {
		t.Fatal("zero price entered free pool")
	}
}
func TestDrainAnchorSurvivesRestartAndEarlierQuotaRecovery(t *testing.T) {
	var restored atomic.Bool
	var first, second atomic.Int64
	h := aggregateFixture(t, func(w http.ResponseWriter, r *http.Request) {
		first.Add(1)
		if !restored.Load() {
			http.Error(w, "exhausted", 402)
			return
		}
		responseFixture(w, r)
	}, func(w http.ResponseWriter, r *http.Request) { second.Add(1); responseFixture(w, r) })
	value := h.Catalog.snapshot()
	value.Models[0].Strategy = "drain"
	if err := h.Catalog.update(context.Background(), value); err != nil {
		t.Fatal(err)
	}
	w := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello"}`)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	restored.Store(true)
	h.routing = routingState{}
	w = catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello"}`)
	if w.Code != 200 || first.Load() != 1 || second.Load() != 2 {
		t.Fatalf("drain reset: %d %d %s", first.Load(), second.Load(), w.Body.String())
	}
}
func TestNestedGroupsAndCatalogCycleRejection(t *testing.T) {
	h := aggregateFixture(t, responseFixture, responseFixture)
	value := h.Catalog.snapshot()
	child := value.Models[0]
	child.ID = "child"
	child.Name = "Child"
	child.Strategy = "weight"
	child.Weights = map[string]int{"work/fixture": 3, "backup/fixture": 1}
	value.Models = append(value.Models, child)
	value.Models[0].Candidates = []ModelCandidate{{groupSource, "child"}}
	if err := h.Catalog.update(context.Background(), value); err != nil {
		t.Fatal(err)
	}
	w := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello"}`)
	if w.Code != 200 {
		t.Fatal(w.Body.String())
	}
	value = h.Catalog.snapshot()
	value.Models[1].Candidates = []ModelCandidate{{groupSource, "coding-main"}}
	value.Models[1].Weights = nil
	if err := h.Catalog.update(context.Background(), value); err == nil || err.Error() != "MODEL_ROUTE_CYCLE" {
		t.Fatalf("cycle accepted: %v", err)
	}
}
func TestSourcePolicyOverridesAndGlobalEditsPreserveIndependentSourceSave(t *testing.T) {
	h := aggregateFixture(t, responseFixture, responseFixture)
	config, _ := h.Ledger.Configuration()
	config.Pricing.Sources["work"] = SourcePricing{Default: PriceRule{Mode: "tokens", Price: ModelPricing{1, 2, .1}}, Models: map[string]PriceRule{"fixture": {Mode: "unknown"}}}
	if err := h.Ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	if _, known := config.Pricing.routePriceAt("work", "fixture", time.Now()); known {
		t.Fatal("unknown override inherited source price")
	}
	legacy := testConfiguration(nil)
	if err := h.Ledger.Configure(legacy); err != nil {
		t.Fatal(err)
	}
	after, _ := h.Ledger.Configuration()
	if after.Pricing.Sources["work"].Default.Price.InputPerMillion != 1 {
		t.Fatal("global save removed source policy")
	}
}
func TestQualityProbeUsesActualResponsesAndDoesNotStorePayloads(t *testing.T) {
	var question atomic.Int64
	handler := func(w http.ResponseWriter, r *http.Request) {
		question.Add(1)
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("data: {\"type\":\"response.output_text.delta\",\"output_index\":0,\"content_index\":0,\"delta\":\"2\"}\n\ndata: {\"type\":\"response.completed\",\"response\":{\"id\":\"response-fixture\",\"status\":\"completed\",\"output\":[{\"type\":\"message\",\"role\":\"assistant\",\"content\":[{\"type\":\"output_text\",\"text\":\"2\"}]}],\"usage\":{\"input_tokens\":8,\"output_tokens\":1}}}\n\n"))
	}
	h := aggregateFixture(t, handler, handler)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/v1/model-gateway/monitor/check", strings.NewReader(`{"sourceId":"work","model":"fixture","rule":"answer"}`)))
	if w.Code != 200 {
		t.Fatalf("probe %d %s", w.Code, w.Body.String())
	}
	var result struct {
		Data MonitorRecord `json:"data"`
	}
	if json.Unmarshal(w.Body.Bytes(), &result) != nil || result.Data.Quality != "pass" || question.Load() != 1 {
		t.Fatalf("probe result %s", w.Body.String())
	}
	rows, _, _ := h.Monitor.Snapshot()
	if len(rows) != 1 || rows[0].QualityRule != "answer" {
		t.Fatal("probe not monitored")
	}
	raw, _ := json.Marshal(rows)
	if strings.Contains(string(raw), "Compute") || strings.Contains(string(raw), "messages") || strings.Contains(string(raw), "output_text") {
		t.Fatal("payload persisted in monitor")
	}
}
