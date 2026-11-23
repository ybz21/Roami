package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
)

func TestAggregationMonitorScopesRequestTrendsBySavedRouteID(t *testing.T) {
	now := time.Date(2026, time.November, 21, 12, 0, 0, 0, time.UTC)
	store, err := monitor.Open(filepath.Join(t.TempDir(), "monitor.ring"), 20, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	gateway := &Handler{Monitor: store}
	pool := CatalogModel{ID: "pool-a", Name: "Identical display name", Aggregate: true}
	others := []CatalogModel{
		{ID: "pool-ab", Name: pool.Name, Aggregate: true},
		{ID: "member", Name: pool.Name},
	}
	member := ModelCandidate{SourceID: "source", Model: "native"}
	observe := func(route CatalogModel, offset time.Duration, status int, tried ...ModelCandidate) {
		t.Helper()
		response := &observedRequestWriter{ResponseWriter: httptest.NewRecorder()}
		request := newRequestObservation(response, ModelCatalog{}, route, "external")
		request.At = now.Add(offset).UnixMilli()
		for i, candidate := range tried {
			success := i == len(tried)-1 && status == http.StatusOK
			request.attempt(monitor.Record{Success: success}, candidate, nil, success, false)
		}
		response.WriteHeader(status)
		request.finish(httptest.NewRequest(http.MethodPost, "/v1/chat/completions", nil), response, gateway)
	}
	observe(pool, -4*time.Minute, http.StatusOK, member)
	observe(pool, -8*time.Minute, http.StatusOK, member, ModelCandidate{SourceID: "source", Model: "backup"})
	observe(pool, -12*time.Minute, http.StatusBadGateway, member, ModelCandidate{SourceID: "other", Model: "backup"})
	observe(pool, -2*time.Hour, http.StatusOK, member)
	for _, route := range others {
		observe(route, -3*time.Minute, http.StatusOK, member)
	}
	if err := store.Append(monitor.Record{At: now.UnixMilli(), RouteID: pool.ID, RequestID: uuid.NewString(), SourceID: member.SourceID, Model: member.Model, Attempt: 1, Quality: "unchecked"}); err != nil {
		t.Fatal(err)
	}

	for _, tc := range []struct {
		route, hours string
		want         monitor.RequestTotals
	}{
		{pool.ID, "1", monitor.RequestTotals{Requests: 3, Failed: 1, Recovered: 1, SameSource: 1, CrossSource: 1, SwitchedFailed: 1}},
		{pool.ID, "6", monitor.RequestTotals{Requests: 4, Failed: 1, Recovered: 1, SameSource: 1, CrossSource: 1, SwitchedFailed: 1}},
		{others[0].ID, "24", monitor.RequestTotals{Requests: 1}},
		{"pool-empty", "24", monitor.RequestTotals{}},
	} {
		t.Run(tc.route+"/"+tc.hours, func(t *testing.T) {
			query := url.Values{"view": {"request-summary"}, "routeId": {tc.route}, "hours": {tc.hours}}
			recorder := httptest.NewRecorder()
			gateway.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor?"+query.Encode(), nil))
			var reply struct {
				Data struct {
					Totals monitor.RequestTotals
					Points []monitor.RequestBucket
				}
			}
			if err := json.Unmarshal(recorder.Body.Bytes(), &reply); err != nil || recorder.Code != http.StatusOK {
				t.Fatalf("monitor status = %d %s (%v)", recorder.Code, recorder.Body.String(), err)
			}
			if got := reply.Data.Totals; got != tc.want {
				t.Errorf("totals = %+v, want %+v", got, tc.want)
			}
			points := reply.Data.Points
			if len(points) != 6 {
				t.Fatalf("got %d trend buckets", len(points))
			}
			if tc.route == pool.ID && tc.hours == "1" {
				if got := points[4].Totals; got != (monitor.RequestTotals{Requests: 1, Failed: 1, CrossSource: 1, SwitchedFailed: 1}) {
					t.Errorf("earlier bucket = %+v", got)
				}
				if got := points[5].Totals; got != (monitor.RequestTotals{Requests: 2, Recovered: 1, SameSource: 1}) {
					t.Errorf("latest bucket = %+v", got)
				}
			}
		})
	}
}

func TestAggregationTraceTracksNestedFailoverThroughPoolRename(t *testing.T) {
	h := aggregateFixture(t, func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "rate limited", http.StatusTooManyRequests)
	}, responseFixture)
	catalog := h.Catalog.snapshot()
	root := &catalog.Models[0]
	backup := root.Candidates[1]
	root.Strategy = "order"
	root.Candidates[1] = ModelCandidate{SourceID: groupSource, Model: "overflow"}
	catalog.Models = append(catalog.Models,
		CatalogModel{ID: "overflow", Name: "Overflow", Aggregate: true, Protocol: root.Protocol, Strategy: "order", Candidates: []ModelCandidate{{SourceID: groupSource, Model: "backup-pool"}}},
		CatalogModel{ID: "backup-pool", Name: "Backup pool", Aggregate: true, Protocol: root.Protocol, Strategy: "order", Candidates: []ModelCandidate{backup}},
	)
	if err := h.Catalog.update(context.Background(), catalog); err != nil {
		t.Fatal(err)
	}
	response := catalogRequest(h, "/v1/responses", `{"model":"coding-main","input":"hello"}`)
	id := response.Header().Get(requestHeader)
	if response.Code != http.StatusOK || id == "" {
		t.Fatalf("inference = %d %s", response.Code, response.Body)
	}
	catalog = h.Catalog.snapshot()
	catalog.Models[0].ID = "coding-renamed"
	catalog.Models[0].Aliases = []string{"coding-main"}
	if err := h.Catalog.update(context.Background(), catalog); err != nil {
		t.Fatal(err)
	}
	for _, row := range []monitor.Record{
		{RouteID: "coding-renamed", Outcome: "success"},
		{RouteID: "overflow", Outcome: "failed", Switch: "source"},
		{RouteID: "coding-main", Outcome: "failed", Switch: "model"},
		{RouteID: "coding-renamed", Outcome: "cancelled", Switch: "source"},
	} {
		row.RequestID, row.At, row.Quality = uuid.NewString(), h.state.now().UnixMilli(), "unchecked"
		if err := h.Monitor.Append(row); err != nil {
			t.Fatal(err)
		}
	}
	getMonitor := func(suffix string, dst any) int {
		t.Helper()
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor"+suffix, nil))
		if dst != nil {
			if err := json.Unmarshal(w.Body.Bytes(), dst); err != nil || w.Code != http.StatusOK {
				t.Fatalf("monitor %s = %d %s (%v)", suffix, w.Code, w.Body, err)
			}
		}
		return w.Code
	}
	summary := readRequestSummary(t, h, url.Values{"routeId": {"coding-renamed"}})
	if summary.Totals != (monitor.RequestTotals{Requests: 4, Failed: 1, Recovered: 1, Uncertain: 1, SameSource: 1, CrossSource: 2, SwitchedFailed: 1}) {
		t.Fatalf("summary = %+v", summary.Totals)
	}
	for filter, want := range map[string]int{"any": 3, "failed": 1} {
		var list struct {
			Data struct{ Recent []monitor.Record }
		}
		getMonitor("?view=requests&routeId=coding-renamed&switch="+filter, &list)
		if len(list.Data.Recent) != want {
			t.Fatalf("switch=%s: %+v", filter, list.Data.Recent)
		}
		if filter == "failed" && list.Data.Recent[0].Outcome != "failed" {
			t.Fatalf("failure filter: %+v", list.Data.Recent)
		}
	}
	var detail struct {
		Data struct {
			Request  monitor.Record
			Attempts []monitor.Record
			Complete bool
		}
	}
	getMonitor("/requests/"+id+"?routeId=coding-renamed", &detail)
	if detail.Data.Request.Outcome != "recovered" || !detail.Data.Complete || len(detail.Data.Attempts) != 2 {
		t.Fatalf("request = %+v", detail.Data)
	}
	slices.SortFunc(detail.Data.Attempts, func(a, b monitor.Record) int { return a.Attempt - b.Attempt })
	first, second := detail.Data.Attempts[0], detail.Data.Attempts[1]
	if first.Status != http.StatusTooManyRequests || len(first.GroupPath) != 0 ||
		!second.Success || !slices.Equal(second.GroupPath, []string{"overflow", "backup-pool"}) {
		t.Fatalf("attempts = %+v", detail.Data.Attempts)
	}
	if status := getMonitor("/requests/"+id+"?routeId=overflow", nil); status != http.StatusNotFound {
		t.Fatalf("request within wrong root pool = %d", status)
	}
}
