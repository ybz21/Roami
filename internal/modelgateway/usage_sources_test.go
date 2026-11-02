package modelgateway

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http/httptest"
	"strconv"
	"testing"
)

func TestUsageSourceFilteringIncludesLegacySessionsAndFiltersBeforeRecentLimit(t *testing.T) {
	l := newLedger(t)
	if err := l.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 30; i++ {
		role, session := "main", ""
		if i == 0 {
			session = "rsi-legacy"
		}
		if i == 1 {
			role = "rsi_artifact_a"
		}
		if i == 2 {
			role = "rsiXmain"
			session = "rsiXlegacy"
		}
		call, err := l.Admit(role, "fixture", session, fmt.Sprint(i))
		if err != nil {
			t.Fatal(err)
		}
		if err = l.Settle(call, &Usage{100, 20, 10}, 200, "", false); err != nil {
			t.Fatal(err)
		}
	}
	// Pending and unknown receipts must retain their source and incomplete counts.
	unknown, err := l.Admit("worker", "fixture", "rsi-unknown", "unknown")
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(unknown, nil, 502, "fixture", false); err != nil {
		t.Fatal(err)
	}
	if _, err = l.Admit("rsi_worker", "fixture", "", "pending"); err != nil {
		t.Fatal(err)
	}
	h := NewHandler(l)
	type group struct {
		Source, Role, Cost                                       string
		Requests, InputTokens, CacheReadTokens, Pending, Unknown int64
	}
	type call struct{ Source, Role, SessionID string }
	type response struct {
		Data struct {
			Today, Groups, Hourly []group
			Recent                []call
		}
	}
	read := func(source string) response {
		t.Helper()
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/usage?days=1&source="+source, nil))
		if w.Code != 200 {
			t.Fatalf("source %q: %d %s", source, w.Code, w.Body.String())
		}
		var r response
		if err := json.Unmarshal(w.Body.Bytes(), &r); err != nil {
			t.Fatal(err)
		}
		return r
	}
	for _, source := range []string{"", "rsi", "other"} {
		r := read(source)
		var global, period, hourly, pending, unknown, input, cached int64
		var cost float64
		for _, g := range r.Data.Today {
			global += g.Requests
		}
		for _, g := range r.Data.Groups {
			if g.Source != "rsi" && g.Source != "other" {
				t.Fatalf("missing source: %+v", g)
			}
			if source != "" && g.Source != source {
				t.Fatalf("mixed source: %+v", g)
			}
			input += g.InputTokens
			cached += g.CacheReadTokens
			fee, err := strconv.ParseFloat(g.Cost, 64)
			if err != nil {
				t.Fatal(err)
			}
			cost += fee
			period += g.Requests
			pending += g.Pending
			unknown += g.Unknown
		}
		for _, g := range r.Data.Hourly {
			if source != "" && g.Source != source {
				t.Fatalf("mixed hour source: %+v", g)
			}
			hourly += g.Requests
		}
		want := int64(32)
		if source == "rsi" {
			want = 4
		}
		if source == "other" {
			want = 28
		}
		completed := int64(30)
		if source == "rsi" {
			completed = 2
		}
		if source == "other" {
			completed = 28
		}
		if input != completed*100 || cached != completed*10 || math.Abs(cost-float64(completed)*0.00027) > 1e-12 {
			t.Fatalf("source %q lost tokens/cost: input=%d cached=%d cost=%f", source, input, cached, cost)
		}
		if global != 32 || period != want || hourly != want {
			t.Fatalf("source %q global=%d period=%d hourly=%d", source, global, period, hourly)
		}
		if source == "rsi" && (pending != 1 || unknown != 1 || len(r.Data.Recent) != 4) {
			t.Fatalf("RSI receipts lost: %+v", r)
		}
		if source == "other" && len(r.Data.Recent) != 20 {
			t.Fatalf("recent limit: %+v", r)
		}
		for _, c := range r.Data.Recent {
			if source != "" && c.Source != source {
				t.Fatalf("mixed recent: %+v", c)
			}
		}
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/usage?source=production", nil))
	if w.Code != 400 {
		t.Fatalf("invalid source accepted: %d", w.Code)
	}
}

func TestUsageSourceQueriesCannotSeparateDailyAdmission(t *testing.T) {
	l := newLedger(t)
	limit := 2.0
	if err := l.Configure(testConfiguration(&limit)); err != nil {
		t.Fatal(err)
	}
	for _, session := range []string{"", "rsi-legacy"} {
		call, err := l.Admit("main", "fixture", session, "")
		if err != nil {
			t.Fatal(err)
		}
		if err = l.Settle(call, &Usage{500000, 0, 0}, 200, "", false); err != nil {
			t.Fatal(err)
		}
	}
	h := NewHandler(l)
	for _, source := range []string{"rsi", "other"} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/usage?source="+source, nil))
		if w.Code != 200 {
			t.Fatal(w.Body.String())
		}
		if _, err := l.Admit("rsi_worker", "fixture", "rsi-next", ""); err == nil || err.Error() != "MODEL_PROXY_DAILY_LIMIT" {
			t.Fatalf("global quota bypass: %v", err)
		}
	}
}
