package service

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/monitor"
	"github.com/ybz21/Roami/internal/modelgateway/routing"
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
	value.Models[0].Strategy = "smart"
	value.Models[0].Candidates = append(value.Models[0].Candidates, ModelCandidate{"backup", "fixture"})
	if err := h.Catalog.update(context.Background(), value); err != nil {
		t.Fatal(err)
	}
	config := testConfiguration(nil)
	config.Pricing.Sources = map[string]SourcePricing{"work": {Default: PriceRule{Mode: "free", Confirmed: true}}, "backup": {Default: PriceRule{Mode: "free", Confirmed: true}}}
	if err := h.state.accounting.Configure(config); err != nil {
		t.Fatal(err)
	}
	store, err := monitor.Open(filepath.Join(t.TempDir(), "monitor.ring"), 100, h.state.now)
	if err != nil {
		t.Fatal(err)
	}
	h.Monitor = store
	t.Cleanup(func() { _ = store.Close() })
	return h
}
func responseFixture(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"id":"r","object":"response","status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"output_text","text":"2"}]}],"usage":{"input_tokens":4,"output_tokens":1}}`))
}

func TestRoutingChecksAPIMemberCapabilitiesAutomatically(t *testing.T) {
	var reads, calls atomic.Int64
	h := aggregateFixture(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodGet && r.URL.Path == "/models" {
			reads.Add(1)
			_, _ = w.Write([]byte(`{"data":[{"id":"fixture","context_length":64000,"supported_parameters":["tools"]}]}`))
			return
		}
		calls.Add(1)
		responseFixture(w, r)
	}, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.Path != "/models" {
			t.Errorf("status check sent %s %s", r.Method, r.URL.Path)
		}
		_, _ = w.Write([]byte(`{"data":[{"id":"fixture","context_length":32000,"supported_parameters":[]}]}`))
	})
	catalog := h.Catalog.snapshot()
	catalog.Models[0].RequireTools = true
	catalog.Models[0].MinContext = 16000
	if err := h.Catalog.update(context.Background(), catalog); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		w := httptest.NewRecorder()
		h.routingView(w, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/catalog/routing?model=coding-main", nil))
		var response struct {
			Data struct {
				Available int
				Members   []struct {
					SourceID string
					Block    string
					Context  int
				}
			}
		}
		if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil ||
			w.Code != http.StatusOK || response.Data.Available != 1 || len(response.Data.Members) != 2 {
			t.Fatalf("routing status = %d %s; %v", w.Code, w.Body.String(), err)
		}
		first, second := response.Data.Members[0], response.Data.Members[1]
		if first.SourceID != "work" || first.Block != "" || first.Context != 64000 ||
			second.SourceID != "backup" || second.Block != "tools" || second.Context != 32000 {
			t.Fatalf("members: %+v", response.Data.Members)
		}
	}
	if reads.Load() != 1 || calls.Load() != 0 {
		t.Fatalf("status did not reuse directory or sent inference: reads=%d calls=%d", reads.Load(), calls.Load())
	}
	w := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello"}`)
	if w.Code != http.StatusOK || calls.Load() != 1 || reads.Load() != 1 {
		t.Fatalf("dispatch did not use the same checked capability: %d %s", w.Code, w.Body.String())
	}
}

func TestAggregateRoutesImagesWithoutSendingThemToTextOnlyModels(t *testing.T) {
	for _, fixture := range []struct {
		name, directory string
		status, hits    int
	}{
		{"advertised image support", `"architecture":{"input_modalities":["text","image"]}`, 200, 1},
		{"unknown support", `"name":"Fixture"`, 200, 1},
		{"only text models", `"architecture":{"input_modalities":["text"]}`, 503, 0},
	} {
		t.Run(fixture.name, func(t *testing.T) {
			var textRequests, imageRequests, directoryRequests atomic.Int64
			h := aggregateFixture(t, func(w http.ResponseWriter, r *http.Request) {
				if r.Method == http.MethodGet {
					directoryRequests.Add(1)
					_, _ = io.WriteString(w, `{"data":[{"id":"fixture","architecture":{"input_modalities":["text"]}}]}`)
					return
				}
				textRequests.Add(1)
				responseFixture(w, r)
			}, func(w http.ResponseWriter, r *http.Request) {
				if r.Method == http.MethodGet {
					directoryRequests.Add(1)
					_, _ = io.WriteString(w, `{"data":[{"id":"fixture",`+fixture.directory+`}]}`)
					return
				}
				imageRequests.Add(1)
				data, err := io.ReadAll(r.Body)
				if err != nil || !strings.Contains(string(data), "data:image/png;base64,ZmFrZQ==") {
					t.Errorf("lost image in upstream conversion: %s (%v)", data, err)
				}
				responseFixture(w, r)
			})
			catalog := h.Catalog.snapshot()
			catalog.Models[0].Strategy = "order"
			if err := h.Catalog.update(context.Background(), catalog); err != nil {
				t.Fatal(err)
			}
			text := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"text only"}`)
			if text.Code != 200 || textRequests.Load() != 1 || directoryRequests.Load() != 0 {
				t.Fatalf("changed text routing or added a directory fetch: %d %s", text.Code, text.Body)
			}
			reply := requestWithKey(h, h.Catalog.credential("claude"), "/v1/messages",
				`{"model":"coding-main","max_tokens":100,"messages":[{"role":"assistant","content":[{"type":"tool_use","id":"a","name":"read","input":{}}]},{"role":"user","content":[{"type":"tool_result","tool_use_id":"a","content":[{"type":"image","source":{"type":"base64","media_type":"image/png","data":"ZmFrZQ=="}}]}]}]}`)
			if reply.Code != fixture.status || int(imageRequests.Load()) != fixture.hits || textRequests.Load() != 1 || directoryRequests.Load() != 2 {
				t.Fatalf("image routing: %d %s, primary=%d backup=%d directory=%d",
					reply.Code, reply.Body, textRequests.Load(), imageRequests.Load(), directoryRequests.Load())
			}
			if fixture.status == http.StatusServiceUnavailable {
				rows, _, err := h.Monitor.Snapshot()
				if err != nil || len(rows) != 3 || rows[2].Blocks["image"] != 2 || rows[2].Attempts != 0 {
					t.Fatalf("image routing block is missing: %+v (%v)", rows, err)
				}
			}
		})
	}
}
func TestAggregateRetriesRejectedSourceHonorsCooldownAndKeepsAttempts(t *testing.T) {
	var first, second atomic.Int64
	h := aggregateFixture(t, func(w http.ResponseWriter, r *http.Request) {
		first.Add(1)
		w.Header().Set("Retry-After", "120")
		http.Error(w, `{"error":{"code":"rate_limit"}}`, 429)
	}, func(w http.ResponseWriter, r *http.Request) { second.Add(1); responseFixture(w, r) })
	var recoveredID string
	for i := 0; i < 2; i++ {
		w := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello"}`)
		if w.Code != 200 {
			t.Fatalf("status=%d body=%s", w.Code, w.Body.String())
		}
		id := w.Header().Get(requestHeader)
		if id == "" || id == recoveredID {
			t.Fatalf("missing distinct gateway reference: %q", id)
		}
		if i == 0 {
			recoveredID = id
		}
	}
	if first.Load() != 1 || second.Load() != 2 {
		t.Fatalf("cooldown not honored: %d %d", first.Load(), second.Load())
	}
	view := httptest.NewRecorder()
	h.ServeHTTP(view, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/catalog/routing?model=coding-main", nil))
	var routingData struct {
		Data struct{ Channels []routing.ChannelStatus }
	}
	if err := json.Unmarshal(view.Body.Bytes(), &routingData); err != nil || view.Code != http.StatusOK {
		t.Fatalf("routing status: %d %s", view.Code, view.Body)
	}
	var rest *int64
	for _, channel := range routingData.Data.Channels {
		if channel.SourceID == "work" {
			rest = channel.RestUntil
		}
	}
	if rest == nil || time.UnixMilli(*rest).Sub(h.state.now()) < 110*time.Second {
		t.Fatal("ignored Retry-After")
	}
	rows, _, err := h.Monitor.Snapshot()
	if err != nil || len(rows) != 5 || rows[0].Success || !rows[1].Success || rows[2].Outcome != "recovered" || rows[4].Outcome != "success" {
		t.Fatalf("attempt and request monitoring: %+v %v", rows, err)
	}
	detail := httptest.NewRecorder()
	h.ServeHTTP(detail, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor/requests/"+recoveredID, nil))
	var result struct {
		Data struct {
			Request  monitor.Record
			Attempts []monitor.Record
			Complete bool
		}
	}
	if err := json.Unmarshal(detail.Body.Bytes(), &result); err != nil || detail.Code != 200 || !result.Data.Complete ||
		result.Data.Request.Switch != "source" || len(result.Data.Attempts) != 2 || result.Data.Attempts[0].Status != 429 || result.Data.Attempts[1].Status != 200 {
		t.Fatalf("request audit: %d %s (%v)", detail.Code, detail.Body.String(), err)
	}
	summaryResponse := httptest.NewRecorder()
	h.ServeHTTP(summaryResponse, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor?view=requests&routeId=coding-main", nil))
	var summary struct {
		Data struct{ Totals monitor.RequestTotals }
	}
	if err := json.Unmarshal(summaryResponse.Body.Bytes(), &summary); err != nil || summaryResponse.Code != 200 ||
		summary.Data.Totals.Requests != 2 || summary.Data.Totals.Failed != 0 || summary.Data.Totals.Recovered != 1 {
		t.Fatalf("request totals: %d %s (%v)", summaryResponse.Code, summaryResponse.Body.String(), err)
	}
	var count int
	if err = h.state.db.QueryRow(`SELECT count(*) FROM gateway_calls`).Scan(&count); err != nil || count != 3 {
		t.Fatal("attempts were not independently accounted")
	}
}

func TestAggregateRequestRejectionDoesNotRetryOrCoolDown(t *testing.T) {
	for _, status := range []int{http.StatusBadRequest, http.StatusRequestEntityTooLarge, http.StatusUnsupportedMediaType, http.StatusUnprocessableEntity} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			var primary, backup atomic.Int64
			h := aggregateFixture(t, func(w http.ResponseWriter, r *http.Request) {
				if primary.Add(1) == 1 {
					http.Error(w, "invalid request", status)
					return
				}
				responseFixture(w, r)
			}, func(w http.ResponseWriter, r *http.Request) {
				backup.Add(1)
				responseFixture(w, r)
			})
			catalog := h.Catalog.snapshot()
			catalog.Models[0].Strategy = "order"
			if err := h.Catalog.update(context.Background(), catalog); err != nil {
				t.Fatal(err)
			}
			bad := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"rejected"}`)
			if bad.Code != status || primary.Load() != 1 || backup.Load() != 0 {
				t.Fatalf("rejected request = %d, primary = %d, backup = %d", bad.Code, primary.Load(), backup.Load())
			}
			good := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"valid"}`)
			if good.Code != http.StatusOK || primary.Load() != 2 || backup.Load() != 0 {
				t.Fatalf("next request = %d, primary = %d, backup = %d", good.Code, primary.Load(), backup.Load())
			}
			rows, _, err := h.Monitor.Snapshot()
			if err != nil || len(rows) != 4 || rows[1].Outcome != "failed" || rows[1].Status != status || rows[1].Attempts != 1 || rows[1].Switch != "" || rows[3].Outcome != "success" {
				t.Fatalf("request observation = %+v (%v)", rows, err)
			}
		})
	}
}

func TestGatewayAuditKeepsTheStructuredRejectionAcrossProtocolBridge(t *testing.T) {
	var backups atomic.Int64
	h := aggregateFixture(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadRequest)
		_, _ = w.Write([]byte(`{"error":{"code":400,"message":"private-upstream-value","metadata":{"raw":"{\"error\":{\"code\":\"context_length_exceeded\"}}"}}}`))
	}, func(w http.ResponseWriter, r *http.Request) {
		backups.Add(1)
		responseFixture(w, r)
	})
	catalog := h.Catalog.snapshot()
	catalog.Models[0].Strategy = "order"
	if err := h.Catalog.update(context.Background(), catalog); err != nil {
		t.Fatal(err)
	}
	reply := requestWithKey(h, h.Catalog.credential("claude"), "/v1/messages",
		`{"model":"coding-main","messages":[{"role":"user","content":"hello"}],"max_tokens":100}`)
	if reply.Code != http.StatusBadRequest || backups.Load() != 0 || strings.Contains(reply.Body.String(), "private-upstream-value") {
		t.Fatalf("unexpected inference response: %d %s, backups=%d", reply.Code, reply.Body, backups.Load())
	}
	detail := httptest.NewRecorder()
	h.ServeHTTP(detail, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor/requests/"+reply.Header().Get(requestHeader), nil))
	var result struct {
		Data struct {
			Request  monitor.Record
			Attempts []monitor.Record
		}
	}
	if err := json.Unmarshal(detail.Body.Bytes(), &result); err != nil || detail.Code != http.StatusOK ||
		result.Data.Request.UpstreamRejection != "context_limit" || result.Data.Request.Error != "MODEL_HTTP_400" ||
		len(result.Data.Attempts) != 1 || result.Data.Attempts[0].UpstreamRejection != "context_limit" ||
		strings.Contains(detail.Body.String(), "private-upstream-value") {
		t.Fatalf("rejection audit: %d %s (%v)", detail.Code, detail.Body, err)
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
	if len(rows) != 2 || rows[0].Success || rows[1].Outcome != "interrupted" || rows[1].Status != 200 {
		t.Fatalf("incomplete stream: %+v", rows)
	}
	config, _ := h.state.accounting.Configuration()
	config.Pricing.Sources = map[string]SourcePricing{"work": {Default: PriceRule{Mode: "tokens"}}, "backup": {Default: PriceRule{Mode: "unknown"}}}
	if err := h.state.accounting.Configure(config); err != nil {
		t.Fatal(err)
	}
	w = catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello","roami_free_only":true}`)
	if w.Code != 503 || backup.Load() != 0 {
		t.Fatal("zero price entered free pool")
	}
	rows, _, _ = h.Monitor.Snapshot()
	last := rows[len(rows)-1]
	if len(rows) != 3 || last.Outcome != "blocked" || last.Attempts != 0 || last.Blocks["pricing"] != 2 || last.RequestID != w.Header().Get(requestHeader) {
		t.Fatalf("zero-attempt request: %+v", last)
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
	h.routing = routing.Selector{}
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
	config, _ := h.state.accounting.Configuration()
	config.Pricing.Sources["work"] = SourcePricing{Default: PriceRule{Mode: "tokens", Price: ModelPricing{1, 2, .1}}, Models: map[string]PriceRule{"fixture": {Mode: "unknown"}}}
	if err := h.state.accounting.Configure(config); err != nil {
		t.Fatal(err)
	}
	if _, known := config.Pricing.RoutePriceAt("work", "fixture", time.Now()); known {
		t.Fatal("unknown override inherited source price")
	}
	legacy := testConfiguration(nil)
	if err := h.state.accounting.Configure(legacy); err != nil {
		t.Fatal(err)
	}
	after, _ := h.state.accounting.Configuration()
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
		Data monitor.Record `json:"data"`
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

func TestAggregateCompactionFiltersUnsupportedSourceBeforeScheduling(t *testing.T) {
	h := aggregateFixture(t, responseFixture, responseFixture)
	value := h.Catalog.snapshot()
	value.Sources[0].Protocol = "openai-completions"
	value.Models[0].Protocol = "openai-completions"
	if err := h.Catalog.update(context.Background(), value); err != nil {
		t.Fatal(err)
	}
	choice, err := h.newRoutingChoice(context.Background(), h.Catalog.snapshot(), h.Catalog.value.Models[0], routing.Requirements{Protocol: "openai-responses"}, false)
	if err != nil {
		t.Fatal(err)
	}
	leaf, ok, err := choice.Next()
	if err != nil || !ok || leaf.Candidate.SourceID != "backup" {
		t.Fatalf("compaction chose incompatible source: %+v %v", leaf, err)
	}
}

func TestGatewayDefaultDispatchesThroughAggregateAndStopsWhenDisabled(t *testing.T) {
	var calls atomic.Int64
	upstream := func(w http.ResponseWriter, r *http.Request) { calls.Add(1); responseFixture(w, r) }
	h := aggregateFixture(t, upstream, upstream)
	saveNodeModels(t, h.state, map[string]any{"connection": map[string]string{"baseUrl": h.Catalog.baseURL + "/v1"}, "main": map[string]string{"model": "coding-main"}})
	result := catalogRequest(h, "/v1/responses", `{"model":"roami-default","input":"hello"}`)
	if result.Code != 200 || calls.Load() != 1 {
		t.Fatalf("default did not dispatch through the aggregate: %d %s", result.Code, result.Body)
	}
	off := false
	h.Catalog.value.Models[0].Enabled = &off
	result = catalogRequest(h, "/v1/responses", `{"model":"roami-default","input":"hello"}`)
	if result.Code == 200 || calls.Load() != 1 {
		t.Fatal("disabled default dispatched another request")
	}
}
