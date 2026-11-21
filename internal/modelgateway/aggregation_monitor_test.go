package modelgateway

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestAggregationMonitorScopesRequestTrendsBySavedRouteID(t *testing.T) {
	now := time.Date(2026, time.November, 21, 12, 0, 0, 0, time.UTC)
	store, err := openMonitorStore(filepath.Join(t.TempDir(), "monitor.ring"), 20, func() time.Time { return now })
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
			request.attempt(MonitorRecord{Success: success}, candidate, nil, success, false)
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
	if err := store.Append(MonitorRecord{At: now.UnixMilli(), RouteID: pool.ID, RequestID: uuid.NewString(), SourceID: member.SourceID, Model: member.Model, Attempt: 1, Quality: "unchecked"}); err != nil {
		t.Fatal(err)
	}

	for _, tc := range []struct {
		route, hours string
		want         requestTotals
	}{
		{pool.ID, "1", requestTotals{Requests: 3, Failed: 1, Recovered: 1, SameSource: 1, CrossSource: 1}},
		{pool.ID, "6", requestTotals{Requests: 4, Failed: 1, Recovered: 1, SameSource: 1, CrossSource: 1}},
		{others[0].ID, "24", requestTotals{Requests: 1}},
		{"pool-empty", "24", requestTotals{}},
	} {
		t.Run(tc.route+"/"+tc.hours, func(t *testing.T) {
			query := url.Values{"view": {"request-summary"}, "routeId": {tc.route}, "hours": {tc.hours}}
			recorder := httptest.NewRecorder()
			gateway.ServeHTTP(recorder, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor?"+query.Encode(), nil))
			var reply struct {
				Data struct {
					Totals requestTotals
					Points []requestBucket
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
				if got := points[4].Totals; got != (requestTotals{Requests: 1, Failed: 1, CrossSource: 1}) {
					t.Errorf("earlier bucket = %+v", got)
				}
				if got := points[5].Totals; got != (requestTotals{Requests: 2, Recovered: 1, SameSource: 1}) {
					t.Errorf("latest bucket = %+v", got)
				}
			}
		})
	}
}
