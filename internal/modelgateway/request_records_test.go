package modelgateway

import (
	"encoding/json"
	"net/http/httptest"
	"reflect"
	"testing"
	"time"
)

func TestUnknownRequestRecordsPreserveTokensAndRemainDiscoverable(t *testing.T) {
	l := newLedger(t)
	if err := l.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	now := l.now()
	l.now = func() time.Time { now = now.Add(time.Millisecond); return now }
	missing, err := l.Admit("cli_claude", "fixture", "", "client-missing", CallAttribution{AgentKind: "claude"})
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(missing, nil, 0, "MODEL_TRANSPORT_FAILED", false); err != nil {
		t.Fatal(err)
	}
	unpriced, err := l.Admit("cli_claude", "unpriced", "", "client-known-tokens", CallAttribution{AgentKind: "claude"})
	if err != nil {
		t.Fatal(err)
	}
	unpriced.upstream = upstreamReceipt{status: 200, request: "provider-request"}
	if err = l.Settle(unpriced, &Usage{Input: 123, Output: 9, Cached: 0}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 25; i++ {
		call, err := l.Admit("cli_codex", "fixture", "", "", CallAttribution{AgentKind: "codex"})
		if err != nil {
			t.Fatal(err)
		}
		if err = l.Settle(call, &Usage{Input: 10, Output: 2}, 200, "", false); err != nil {
			t.Fatal(err)
		}
	}
	all, err := l.Statistics(1)
	if err != nil || len(all.Recent) != 20 {
		t.Fatalf("recent window: %+v %v", all, err)
	}
	filtered, err := l.StatisticsForCalls(1, "", "", "", "unknown")
	if err != nil || len(filtered.Recent) != 2 || !reflect.DeepEqual(all.Groups, filtered.Groups) || !reflect.DeepEqual(all.Today, filtered.Today) {
		t.Fatalf("record filter changed totals or lost old unknown requests: %+v %v", filtered, err)
	}
	for _, record := range filtered.Recent {
		if record.State != "unknown" || record.Cost != nil {
			t.Fatalf("unknown costs rewritten: %+v", record)
		}
		if record.ID == missing.ID {
			if record.Input != nil || record.Output != nil || record.Cached != nil || record.Request != "client-missing" {
				t.Fatalf("invented missing tokens or lost request ID: %+v", record)
			}
		} else if record.ID != unpriced.ID || record.Input == nil || *record.Input != 123 || record.Output == nil || *record.Output != 9 || record.Cached == nil || *record.Cached != 0 || record.UpstreamRequest != "provider-request" {
			t.Fatalf("known tokens or receipt lost with unknown costs: %+v", record)
		}
	}
	h := NewHandler(l)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/usage?days=1&recentState=unknown&agentKind=claude&source=other", nil))
	var response struct{ Data Statistics }
	if err = json.Unmarshal(w.Body.Bytes(), &response); err != nil || w.Code != 200 || response.Data.RecentState != "unknown" || len(response.Data.Recent) != 2 {
		t.Fatalf("request filter API: %d %s %v", w.Code, w.Body, err)
	}
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/v1/model-gateway/usage?recentState=invalid", nil))
	if w.Code != 400 {
		t.Fatalf("invalid record filter accepted: %d %s", w.Code, w.Body)
	}
}
