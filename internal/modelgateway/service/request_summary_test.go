package service

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/monitor"
)

func readRequestSummary(t *testing.T, h *Handler, query url.Values) monitor.RequestSummary {
	t.Helper()
	query.Set("view", "request-summary")
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor?"+query.Encode(), nil))
	var response struct{ Data monitor.RequestSummary }
	if err := json.Unmarshal(w.Body.Bytes(), &response); err != nil || w.Code != http.StatusOK {
		t.Fatalf("request summary = %d %s (%v)", w.Code, w.Body.String(), err)
	}
	if body := w.Body.String(); strings.Contains(body, `"recent"`) || strings.Contains(body, `"requestId"`) {
		t.Fatalf("summary includes request rows: %s", body)
	}
	return response.Data
}

func TestRequestSummaryUsesTerminalRequestsAndSelectedWindow(t *testing.T) {
	now := time.Date(2026, time.November, 20, 14, 30, 0, 0, time.UTC)
	store, err := monitor.Open(filepath.Join(t.TempDir(), "monitor.ring"), 30, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	h := &Handler{Monitor: store}
	add := func(minutesAgo int, row monitor.Record) {
		t.Helper()
		row.At, row.Quality = now.Add(-time.Duration(minutesAgo)*time.Minute).UnixMilli(), "unchecked"
		if row.RouteID == "" {
			row.RouteID, row.Model = "coding", "Code assistant"
		}
		if row.Caller == "" {
			row.Caller = "external"
		}
		if err := store.Append(row); err != nil {
			t.Fatal(err)
		}
	}
	add(11, monitor.Record{Outcome: "failed", Error: "MODEL_HTTP_429", Status: 429, Attempts: 1, SourceID: "primary"})
	add(10, monitor.Record{Outcome: "success", Duration: 98, SourceID: "primary", TokenUsage: &monitor.TokenUsage{100, 10}})
	add(9, monitor.Record{RequestID: "legacy", Attempt: 1, SourceID: "primary", Duration: 300, FirstToken: floatPointer(40)})
	add(8, monitor.Record{RequestID: "legacy", Attempt: 2, SourceID: "backup", Success: true, FirstToken: floatPointer(120)})
	add(8, monitor.Record{RequestID: "legacy", Outcome: "recovered", Switch: "source", Attempts: 2, SourceID: "backup", Duration: 900})
	add(7, monitor.Record{Outcome: "success", SourceID: "primary", Duration: 500, FirstToken: floatPointer(100), TokenUsage: &monitor.TokenUsage{700, 400}})
	add(6, monitor.Record{Outcome: "failed", Status: 429, Attempts: 1, SourceID: "primary", Duration: 2000})
	add(5, monitor.Record{Outcome: "blocked"})
	add(4, monitor.Record{Outcome: "cancelled", SourceID: "primary"})
	add(3, monitor.Record{Outcome: "success", Caller: "codex", SourceID: "primary", Duration: 400, TokenUsage: &monitor.TokenUsage{900, 800}})
	add(2, monitor.Record{Outcome: "success", RouteID: "other", SourceID: "backup", Duration: 600, TokenUsage: &monitor.TokenUsage{60, 40}})

	from, to := now.Add(-10*time.Minute).UnixMilli(), now.UnixMilli()
	query := url.Values{
		"hours": {"1"}, "routeId": {"coding"}, "caller": {"external"},
		"from": {strconv.FormatInt(from, 10)}, "to": {strconv.FormatInt(to, 10)}, "end": {strconv.FormatInt(to, 10)},
	}
	data := readRequestSummary(t, h, query)
	if data.Range != (monitor.RequestSummaryRange{from, to}) || data.Now != to ||
		data.Totals != (monitor.RequestTotals{Requests: 5, Failed: 2, Recovered: 1, Uncertain: 1, CrossSource: 1}) ||
		len(data.Points) != 6 || data.Points[4].Totals.Requests != 2 || data.Points[5].Totals != data.Totals {
		t.Fatalf("range, totals and buckets = %+v", data)
	}
	if data.FirstToken == nil || *data.FirstToken != (monitor.RequestPercentiles{Samples: 2, P50: 100, P95: 120, P99: 120}) ||
		data.Duration == nil || *data.Duration != (monitor.RequestPercentiles{Samples: 2, P50: 500, P95: 900, P99: 900}) ||
		data.Tokens != (monitor.RequestTokenSummary{TokenUsage: monitor.TokenUsage{700, 400}, Samples: 1}) {
		t.Fatalf("selected latency and token metrics = %+v, %+v, %+v", data.FirstToken, data.Duration, data.Tokens)
	}
	if len(data.ByModel) != 1 || data.ByModel[0] != (monitor.RequestSummaryGroup{ID: "coding", Totals: data.Totals}) ||
		len(data.BySource) != 3 || data.BySource[0].ID != "primary" || data.BySource[0].Totals.Requests != 3 ||
		data.BySource[1].ID != "" || data.BySource[2].ID != "backup" || data.BySource[2].Totals.Recovered != 1 ||
		data.FailureReasons["upstreamLimited"] != 1 || data.FailureReasons["blocked"] != 1 || !data.Callers["codex"] {
		t.Fatalf("model, source and breakdown counts = %+v", data)
	}

	query.Set("reason", "upstreamLimited")
	data = readRequestSummary(t, h, query)
	if data.Totals != (monitor.RequestTotals{Requests: 1, Failed: 1}) || data.Points[4].Totals.Requests != 1 ||
		data.Points[5].Totals != data.Totals || data.FirstToken != nil || data.Duration != nil || data.Tokens.Samples != 0 ||
		len(data.ByModel) != 1 || data.ByModel[0].Totals != data.Totals ||
		len(data.BySource) != 1 || data.BySource[0].ID != "primary" || data.BySource[0].Totals != data.Totals ||
		data.FailureReasons["blocked"] != 1 {
		t.Fatalf("reason-filtered summary = %+v", data)
	}

	query.Del("reason")
	query.Set("outcome", "uncertain")
	data = readRequestSummary(t, h, query)
	if data.Totals != (monitor.RequestTotals{Requests: 1, Uncertain: 1}) || data.Points[4].Totals.Requests != 0 || data.Points[5].Totals != data.Totals {
		t.Fatalf("outcome-filtered summary = %+v", data)
	}
}

func TestRequestSummaryCapturesStreamUsageForRecoveredRequest(t *testing.T) {
	h := aggregateFixture(t, func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "rate limited", http.StatusTooManyRequests)
	}, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = w.Write([]byte("data: {\"type\":\"response.output_text.delta\",\"delta\":\"hello\"}\n\n" +
			"data: {\"type\":\"response.completed\",\"response\":{\"usage\":{\"input_tokens\":112,\"output_tokens\":8}}}\n\n"))
	})
	w := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello","stream":true}`)
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), "hello") {
		t.Fatalf("gateway stream = %d %s", w.Code, w.Body.String())
	}
	data := readRequestSummary(t, h, url.Values{"hours": {"1"}})
	if data.Totals.Requests != 1 || data.Totals.Recovered != 1 ||
		data.FirstToken == nil || data.FirstToken.Samples != 1 || data.Duration == nil || data.Duration.Samples != 1 ||
		data.Tokens != (monitor.RequestTokenSummary{TokenUsage: monitor.TokenUsage{Input: 112, Output: 8}, Samples: 1}) ||
		len(data.BySource) != 1 || data.BySource[0].ID != "backup" {
		t.Fatalf("stream summary = %+v", data)
	}
}
