package service

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"reflect"
	"strconv"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
)

func TestRequestMonitorFiltersFailureReasonsWithinPinnedBucket(t *testing.T) {
	now := time.Date(2026, time.November, 20, 14, 30, 0, 0, time.UTC)
	store, err := monitor.Open(filepath.Join(t.TempDir(), "monitor.ring"), 20, func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	h := &Handler{Monitor: store}
	appendRecord := func(offset time.Duration, outcome string, status, attempts int, code, route string) string {
		t.Helper()
		id := uuid.NewString()
		if err := store.Append(monitor.Record{
			RequestID: id, At: now.Add(offset).UnixMilli(), RouteID: route, Caller: "external",
			Outcome: outcome, Status: status, Attempts: attempts, Error: code, Quality: "unchecked",
		}); err != nil {
			t.Fatal(err)
		}
		return id
	}
	appendRecord(-18*time.Minute, "failed", 429, 1, "MODEL_HTTP_429", "coding")
	atBoundary := appendRecord(-10*time.Minute, "failed", 429, 1, "MODEL_HTTP_429", "coding")
	rateLimited := appendRecord(-8*time.Minute, "failed", 429, 1, "MODEL_HTTP_429", "coding")
	appendRecord(-7*time.Minute, "blocked", 503, 0, "MODEL_ROUTE_NO_AVAILABLE_MEMBER", "coding")
	appendRecord(-6*time.Minute, "interrupted", 200, 1, "MODEL_GATEWAY_INTERRUPTED", "coding")
	appendRecord(-5*time.Minute, "recovered", 200, 2, "", "coding")
	appendRecord(-4*time.Minute, "cancelled", 0, 1, "MODEL_TRANSPORT_FAILED", "coding")
	appendRecord(-3*time.Minute, "failed", 429, 1, "MODEL_HTTP_429", "another-route")

	query := url.Values{
		"view": {"requests"}, "hours": {"1"}, "routeId": {"coding"}, "caller": {"external"},
		"from": {strconv.FormatInt(now.Add(-10*time.Minute).UnixMilli(), 10)},
		"to":   {strconv.FormatInt(now.UnixMilli(), 10)}, "end": {strconv.FormatInt(now.UnixMilli(), 10)},
		"reason": {"upstreamLimited"},
	}
	recorder := httptest.NewRecorder()
	if !h.requestMonitorManagement(recorder, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor?"+query.Encode(), nil)) {
		t.Fatal("monitor route did not handle the request")
	}
	var reply struct {
		Data struct {
			Totals         monitor.RequestTotals
			Points         []monitor.RequestBucket
			FailureReasons map[string]int
			Outcomes       map[string]int
			Recent         []monitor.Record
		}
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &reply); err != nil || recorder.Code != http.StatusOK {
		t.Fatalf("monitor status = %d %s (%v)", recorder.Code, recorder.Body.String(), err)
	}
	data := reply.Data
	if data.Totals.Requests != 7 || len(data.Points) != 6 || data.Points[5].Totals.Requests != 5 ||
		!reflect.DeepEqual(data.FailureReasons, map[string]int{"upstreamLimited": 1, "blocked": 1, "interrupted": 1}) ||
		!reflect.DeepEqual(data.Outcomes, map[string]int{"failed": 1, "blocked": 1, "interrupted": 1, "recovered": 1, "uncertain": 1}) {
		t.Fatalf("sample and trend counts = %+v", data)
	}
	if len(data.Recent) != 1 || data.Recent[0].RequestID != rateLimited || data.Recent[0].RequestID == atBoundary {
		t.Fatalf("filtered request list = %+v", data.Recent)
	}
	detail := httptest.NewRecorder()
	h.requestMonitorManagement(detail, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor/requests/"+data.Recent[0].RequestID, nil))
	var trace struct {
		Data struct{ Request monitor.Record }
	}
	if err := json.Unmarshal(detail.Body.Bytes(), &trace); err != nil || detail.Code != http.StatusOK || trace.Data.Request.RequestID != rateLimited {
		t.Fatalf("filtered request audit = %d %s (%v)", detail.Code, detail.Body.String(), err)
	}
	query.Set("reason", "arbitrary")
	badQuery := httptest.NewRecorder()
	h.requestMonitorManagement(badQuery, httptest.NewRequest(http.MethodGet, "/v1/model-gateway/monitor?"+query.Encode(), nil))
	if badQuery.Code != http.StatusBadRequest {
		t.Fatalf("unsupported reason status = %d", badQuery.Code)
	}
}

func TestRequestMonitorDistinguishesGatewayAndUpstreamFailures(t *testing.T) {
	cases := []struct {
		row  monitor.Record
		want string
	}{
		{monitor.Record{Outcome: "failed", Status: 402, Error: "MODEL_PROXY_DAILY_LIMIT"}, "dailyLimit"},
		{monitor.Record{Outcome: "failed", Status: 402, Attempts: 1, Error: "MODEL_HTTP_402"}, "quota"},
		{monitor.Record{Outcome: "failed", Status: 401, Attempts: 1, Error: "MODEL_GATEWAY_UNAUTHORIZED"}, "failed"},
		{monitor.Record{Outcome: "failed", Status: 401, Attempts: 1, Error: "MODEL_HTTP_401"}, "upstreamUnauthorized"},
		{monitor.Record{Outcome: "failed", Status: 504, Attempts: 1, Error: "MODEL_HTTP_504"}, "upstreamTimeout"},
		{monitor.Record{Outcome: "failed", Status: 502, Attempts: 1, Error: "MODEL_TRANSPORT_FAILED"}, "connectFailed"},
		{monitor.Record{Outcome: "exhausted", Status: 503, Attempts: 3}, "exhausted"},
		{monitor.Record{Outcome: "recovered", Status: 200, Attempts: 2}, ""},
	}
	for _, test := range cases {
		if got := monitor.FailureReason(test.row); got != test.want {
			t.Errorf("%+v: failure reason = %q, want %q", test.row, got, test.want)
		}
	}
}
