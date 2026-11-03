package modelgateway

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

func TestCatalogRejectionDoesNotBlockSharedDailyBudget(t *testing.T) {
	for _, route := range []struct{ agent, protocol, source, path string }{
		{"opencode", "openai-completions", "openai-completions", "/v1/chat/completions"},
		{"codex", "openai-responses", "openai-responses", "/v1/responses"},
		{"claude", "anthropic-messages", "openai-completions", "/v1/messages"},
		{"codex", "openai-responses", "openai-completions", "/v1/responses"},
	} {
		for _, rejection := range []struct {
			name      string
			status    int
			truncated bool
			unknown   bool
		}{
			{"unauthorized", 401, false, false},
			{"forbidden", 403, false, false},
			{"rate-limited", 429, false, false},
			{"server-error", 500, false, true},
			{"truncated-rejection", 401, true, true},
			{"missing-usage", 200, false, true},
		} {
			t.Run(route.agent+"/"+route.source+"/"+rejection.name, func(t *testing.T) {
				var hits atomic.Int32
				upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
					if hits.Add(1) == 1 {
						if rejection.truncated {
							w.Header().Set("Content-Length", "1000")
						}
						w.WriteHeader(rejection.status)
						_, _ = io.WriteString(w, `{"error":{"message":"rejected"}}`)
						return
					}
					_ = json.NewEncoder(w).Encode(fixtureProtocolResponse(route.source))
				}))
				defer upstream.Close()
				h := catalogHandler(t, upstream.URL+"/v1", route.source)
				if err := h.Ledger.Configure(testConfiguration(floatPointer(100))); err != nil {
					t.Fatal(err)
				}
				body, _ := json.Marshal(protocolFixtureRequest(route.protocol, false))
				requestWithKey(h, h.Catalog.credential(route.agent), route.path, string(body))
				stats, err := h.Ledger.Statistics(1)
				if err != nil || len(stats.Recent) != 1 {
					t.Fatalf("missing attempt: %+v %v", stats, err)
				}
				record := stats.Recent[0]
				if record.UpstreamStatus != rejection.status || record.Input != nil {
					t.Fatalf("lost rejection receipt or invented tokens: %+v", record)
				}
				if rejection.unknown {
					if record.State != "unknown" || record.Cost != nil {
						t.Fatalf("uncertain charges treated as free: %+v", record)
					}
				} else if record.State != "failed" || record.Cost == nil || *record.Cost != "0.000000000" || record.Error != fmt.Sprintf("MODEL_HTTP_%d", rejection.status) {
					t.Fatalf("rejected request left unknown charges: %+v", record)
				}
				// The budget is shared: a Claude rejection must not block OpenCode or Codex.
				for _, next := range []struct{ agent, protocol, path string }{
					{"opencode", "openai-completions", "/v1/chat/completions"},
					{"codex", "openai-responses", "/v1/responses"},
				} {
					body, _ := json.Marshal(protocolFixtureRequest(next.protocol, false))
					response := requestWithKey(h, h.Catalog.credential(next.agent), next.path, string(body))
					if response.Code != 200 {
						t.Fatalf("rejection blocked %s: %d %s", next.agent, response.Code, response.Body)
					}
				}
				stats, err = h.Ledger.Statistics(1)
				var unknown int64
				for _, group := range stats.Today {
					unknown += group.Unknown
				}
				wantUnknown := int64(0)
				if rejection.unknown {
					wantUnknown = 1
				}
				if err != nil || hits.Load() != 3 || len(stats.Recent) != 3 || unknown != wantUnknown {
					t.Fatalf("subsequent calls did not settle or lost unknown charge: %+v hits=%d err=%v", stats, hits.Load(), err)
				}
			})
		}
	}
}
