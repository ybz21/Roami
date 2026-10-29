package modelgateway

import (
	"sync"
	"testing"
	"time"

	metadb "github.com/ybz21/Roami/internal/storage"
)

func newLedger(t *testing.T) *Ledger {
	t.Helper()
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	l, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = metadb.Discard(l.db.Path()) })
	l.now = func() time.Time { return time.Date(2026, 10, 29, 12, 0, 0, 0, time.UTC) }
	return l
}

func testConfiguration(limit *float64) Configuration {
	c := defaultConfiguration()
	c.DailyLimit = limit
	c.Pricing.Models["fixture"] = ModelPricing{InputPerMillion: 2, OutputPerMillion: 4, CacheReadPerMillion: 1}
	return c
}

func TestLedgerPriceSnapshotCacheAndDailyQuota(t *testing.T) {
	l := newLedger(t)
	limit := 2.0
	c := testConfiguration(&limit)
	if err := l.Configure(c); err != nil {
		t.Fatal(err)
	}
	call, err := l.Admit("worker", "fixture", "session", "request")
	if err != nil {
		t.Fatal(err)
	}
	// Updating a price cannot change the rate of an already admitted request.
	c.Pricing.Models["fixture"] = ModelPricing{InputPerMillion: 100}
	if err = l.Configure(c); err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(call, &Usage{1_000_000, 125_000, 500_000}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(call, &Usage{1, 1, 0}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	stats, err := l.Statistics(7)
	if err != nil {
		t.Fatal(err)
	}
	if len(stats.Today) != 1 || stats.Today[0].Cost != "2.000000000" || stats.Today[0].Cached != 500_000 || stats.Recent[0].State != "known" {
		t.Fatalf("incorrect bill: %+v", stats)
	}
	if _, err = l.Admit("main", "fixture", "", ""); err == nil || err.Error() != "MODEL_PROXY_DAILY_LIMIT" {
		t.Fatalf("quota: %v", err)
	}
	l.now = func() time.Time { return time.Date(2026, 10, 30, 0, 0, 0, 0, time.UTC) }
	if _, err = l.Admit("memory", "fixture", "", ""); err != nil {
		t.Fatalf("new day: %v", err)
	}
}

func TestLedgerAdmissionIsAtomicAcrossConnections(t *testing.T) {
	l := newLedger(t)
	limit := 5.0
	if err := l.Configure(testConfiguration(&limit)); err != nil {
		t.Fatal(err)
	}
	var wait sync.WaitGroup
	results := make(chan error, 16)
	for i := 0; i < 16; i++ {
		wait.Add(1)
		go func() { defer wait.Done(); _, err := l.Admit("main", "fixture", "", ""); results <- err }()
	}
	wait.Wait()
	close(results)
	admitted := 0
	for err := range results {
		if err == nil {
			admitted++
		} else if err.Error() != "MODEL_PROXY_USAGE_PENDING" {
			t.Fatal(err)
		}
	}
	if admitted != 1 {
		t.Fatalf("admitted %d concurrent limited calls", admitted)
	}
}

func TestLedgerRecoveryUnknownReconciliationAndZeroDefault(t *testing.T) {
	l := newLedger(t)
	limit := 1.0
	if err := l.Configure(testConfiguration(&limit)); err != nil {
		t.Fatal(err)
	}
	call, err := l.Admit("main", "fixture", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Recover(); err != nil {
		t.Fatal(err)
	}
	if _, err = l.Admit("worker", "fixture", "", ""); err == nil || err.Error() != "MODEL_PROXY_USAGE_UNKNOWN" {
		t.Fatalf("unknown call admitted: %v", err)
	}
	if err = l.Reconcile(call.ID, .25, "provider receipt checked"); err != nil {
		t.Fatal(err)
	}
	if err = l.Reconcile(call.ID, 0, "overwrite"); err == nil {
		t.Fatal("known charge overwritten")
	}
	call, err = l.Admit("memory", "unpriced", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(call, nil, 200, "MODEL_PROXY_USAGE_UNKNOWN", false); err != nil {
		t.Fatal(err)
	}
	stats, err := l.Statistics(1)
	if err != nil {
		t.Fatal(err)
	}
	if len(stats.Groups) != 2 {
		t.Fatalf("groups: %+v", stats)
	}
	for _, record := range stats.Recent {
		if record.Model == "unpriced" && (record.State != "known" || record.Cost == nil || *record.Cost != "0.000000000") {
			t.Fatalf("zero-price success: %+v", record)
		}
	}
	if _, err = l.Admit("worker", "fixture", "", ""); err != nil {
		t.Fatalf("zero default blocked: %v", err)
	}
}

func TestCurrencyTimezoneAndConfigurationValidation(t *testing.T) {
	l := newLedger(t)
	c := testConfiguration(nil)
	c.Timezone = "America/New_York"
	if err := l.Configure(c); err != nil {
		t.Fatal(err)
	}
	l.now = func() time.Time { return time.Date(2026, 10, 29, 1, 0, 0, 0, time.UTC) }
	call, err := l.Admit("main", "fixture", "", "")
	if err != nil || call.Day != "2026-10-28" {
		t.Fatalf("timezone: %+v %v", call, err)
	}
	c.Currency = "USD"
	if err = l.Configure(c); err == nil {
		t.Fatal("currency reinterpreted existing day")
	}
	c.Currency, c.Timezone = "CNY", "UTC"
	if err = l.Configure(c); err == nil {
		t.Fatal("timezone change bypassed active period")
	}
	c.Timezone = "not-a-timezone"
	if err = c.validate(); err == nil {
		t.Fatal("invalid zone accepted")
	}
}

func TestIntegerCostPrecisionAndLongestPrefix(t *testing.T) {
	pc := PricingConfig{Models: map[string]ModelPricing{"fixture": {InputPerMillion: 1}, "fixture-long": {InputPerMillion: 2}}}
	for i := 0; i < 100; i++ {
		if pc.Lookup("fixture-long-version").InputPerMillion != 2 {
			t.Fatal("non-deterministic prefix price")
		}
	}
	if got := costNano(ModelPricing{InputPerMillion: .1}, Usage{3, 0, 0}); got != 300 {
		t.Fatalf("decimal cost: %d", got)
	}
}
