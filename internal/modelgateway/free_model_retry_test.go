package modelgateway

import (
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/modelplugins"
)

func TestFreeModelRetryUsesHTTPHeaderOnlyBeforeUpstreamAttempts(t *testing.T) {
	const retryHeader = "Retry-After"
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if hits.Add(1) == 1 {
			w.Header().Set(retryHeader, "120")
			http.Error(w, "rate limited", http.StatusTooManyRequests)
			return
		}
		fmt.Fprint(w, `{"choices":[{"message":{"role":"assistant","content":"ok"}}],"usage":{"prompt_tokens":4,"completion_tokens":1}}`)
	}))
	defer upstream.Close()
	h := catalogHandler(t, upstream.URL, "openai-completions")
	config := testConfiguration(nil)
	config.Pricing.Sources = map[string]SourcePricing{"work": {Default: PriceRule{Mode: "free", Confirmed: true}}}
	if err := h.Ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	saveNodeModels(t, h.Ledger, map[string]any{"connection": map[string]any{"baseUrl": upstream.URL, "apiKey": "fixture"}, "worker": map[string]any{"model": "default-worker"}})
	route, err := readNodeModels(h.Ledger.paths, "worker")
	if err != nil {
		t.Fatal(err)
	}
	clock := time.Now().Truncate(time.Millisecond)
	h.Ledger.now = func() time.Time { return clock }
	call := func(free bool, private bool) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		body := fmt.Sprintf(`{"model":"coding-main","roami_free_only":%t,"messages":[{"role":"user","content":"hello"}]}`, free)
		request := httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(body))
		if private {
			request.Header.Set("X-Roami-Model-Role", "worker")
			request.Header.Set("X-Roami-Model-Route", route.identity())
			h.ServeHTTP(w, request)
		} else {
			request.Header.Set("Authorization", "Bearer "+h.Catalog.credential("roami"))
			h.publicModels(w, request)
		}
		return w
	}
	if first := call(true, true); first.Header().Get(retryHeader) != "" || hits.Load() != 1 {
		t.Fatalf("attempted request acquired a retry receipt: status=%d hits=%d header=%q", first.Code, hits.Load(), first.Header().Get(retryHeader))
	}
	at := clock.Add(120 * time.Second)
	if blocked := call(true, true); blocked.Code != 503 || hits.Load() != 1 || blocked.Header().Get(retryHeader) != "120" {
		t.Fatalf("missing retry delay on the private route: status=%d hits=%d header=%q body=%s", blocked.Code, hits.Load(), blocked.Header().Get(retryHeader), blocked.Body)
	}
	if public := call(true, false); public.Code != 503 || public.Header().Get(retryHeader) != "120" || hits.Load() != 1 {
		t.Fatalf("missing retry delay on the public route: %d %q", public.Code, public.Header().Get(retryHeader))
	}
	clock = at
	if recovered := call(true, true); recovered.Code != 200 || hits.Load() != 2 || recovered.Header().Get(retryHeader) != "" {
		t.Fatalf("did not recover through the original free route: status=%d hits=%d body=%s", recovered.Code, hits.Load(), recovered.Body)
	}
	h.restRoute(routingLeaf{ChannelID: "work/fixture/"}, h.Catalog.snapshot().Models[0], http.StatusUnauthorized, 0)
	if unauthorized := call(true, true); unauthorized.Code != 503 || hits.Load() != 2 || unauthorized.Header().Get(retryHeader) != "" {
		t.Fatalf("authentication cooldown received a free-capacity receipt: %d %q", unauthorized.Code, unauthorized.Header().Get(retryHeader))
	}
	if regular := call(false, false); regular.Header().Get(retryHeader) != "" {
		t.Fatalf("regular route received a free-capacity hint: %d %q", regular.Code, regular.Header().Get(retryHeader))
	}
}

func TestFreeModelRetryNeedsEveryApplicableDepletedWindowReset(t *testing.T) {
	now := time.Date(2026, time.November, 21, 12, 0, 0, 0, time.UTC)
	soon, late := now.Add(time.Hour), now.Add(2*time.Hour)
	zero := float64(0)
	quota := modelplugins.Quota{ObservedAt: now.UnixMilli(), Windows: []modelplugins.QuotaWindow{
		{Name: "Weekly", Balance: &zero, ResetsAt: soon.Format(time.RFC3339)},
		{Name: "5h", Balance: &zero, ResetsAt: late.Format(time.RFC3339)},
		{Model: "other", Balance: &zero},
	}}
	if result := quotaForModel(quota, "fixture", now); !result.RetryAt.Equal(late) || !result.Reset.Equal(soon) {
		t.Fatalf("retry time must honor both windows without changing the existing primary reset: %+v", result)
	}
	quota.Windows[1].ResetsAt = ""
	if result := quotaForModel(quota, "fixture", now); !result.RetryAt.IsZero() {
		t.Fatalf("depleted window with unknown reset must not advertise retry: %+v", result)
	}
}
