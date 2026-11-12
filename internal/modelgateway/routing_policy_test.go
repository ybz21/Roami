package modelgateway

import (
	"github.com/ybz21/Roami/internal/modelplugins"
	"testing"
	"time"
)

func routeNumber(value float64) *float64 { return &value }
func routeFixture(id string, remaining float64, reset time.Time) routeTarget {
	return routeTarget{ID: id, Member: id, Kind: "account", Weight: 1, Quota: routingQuota{Remaining: routeNumber(remaining), Capacity: routeNumber(100), Reset: reset}}
}
func TestRoutingQuotaOrderAndPace(t *testing.T) {
	now := time.Date(2026, 11, 12, 12, 0, 0, 0, time.UTC)
	weekly := routeFixture("weekly", 80, now.Add(72*time.Hour))
	five := routeFixture("five", 50, now.Add(2*time.Hour))
	reserve := routeFixture("reserve", 5, now.Add(time.Minute))
	memory := &routeMemory{Weights: map[string]int64{}}
	if got := rankRouteTargets("smart", []routeTarget{weekly, five}, now, memory)[0].ID; got != "five" {
		t.Fatal(got)
	}
	monthlyA, monthlyB := weekly, weekly
	monthlyA.ID, monthlyB.ID = "month-a", "month-b"
	monthlyA.Quota.Credits = []creditExpiry{{10, now.Add(48 * time.Hour)}}
	monthlyB.Quota.Credits = []creditExpiry{{5, now.Add(24 * time.Hour)}}
	points := routeFixture("pack", 90, time.Time{})
	points.Quota.Credits = []creditExpiry{{20, now.Add(12 * time.Hour)}}
	got := rankRouteTargets("smart", []routeTarget{monthlyA, monthlyB, points}, now, memory)
	if got[0].ID != "pack" || got[1].ID != "month-b" {
		t.Fatalf("credits: %+v", got)
	}
	got = rankRouteTargets("pace", []routeTarget{weekly, reserve, five}, now, memory)
	if got[0].ID != "five" || got[2].ID != "reserve" {
		t.Fatal("pace or reserve ordering")
	}
	weekly.Quota.Credits = []creditExpiry{{30, now.Add(time.Hour)}, {1000, now.Add(24 * time.Hour)}}
	if rate := quotaUrgency(weekly.Quota, now); rate != 30 {
		t.Fatal(rate)
	}
	keyA, keyB := weekly, five
	keyA.Kind, keyB.Kind = "key", "key"
	keyA.Channel.Input, keyB.Channel.Input = 20000, 1000
	if rankRouteTargets("pace", []routeTarget{keyA, keyB}, now, memory)[0].ID != keyB.ID {
		t.Fatal("key token order")
	}
	unknown := routeFixture("unknown", 0, time.Time{})
	unknown.Quota.Remaining = nil
	if rankRouteTargets("usage", []routeTarget{unknown, five, weekly}, now, memory)[0].ID != weekly.ID {
		t.Fatal("remaining quota")
	}
}
func TestRoutingDrainRotateAndWeights(t *testing.T) {
	now := time.Now()
	a, b := routeFixture("a", 100, now.Add(time.Hour)), routeFixture("b", 100, now.Add(2*time.Hour))
	state := routingState{}
	memory := &routeMemory{Weights: map[string]int64{}}
	model := CatalogModel{ID: "pool", Strategy: "drain"}
	if err := state.reserve(model, []routeTarget{a, b}, a, memory, true, nil, now); err != nil {
		t.Fatal(err)
	}
	a.Channel.RestUntil = now.Add(time.Hour)
	if err := state.reserve(model, []routeTarget{a, b}, b, memory, false, nil, now); err != nil {
		t.Fatal(err)
	}
	if memory.Anchor != "a" {
		t.Fatal("temporary cooldown moved anchor")
	}
	a.Channel.ExhaustedUntil = now.Add(time.Hour)
	if err := state.reserve(model, []routeTarget{a, b}, b, memory, false, nil, now); err != nil {
		t.Fatal(err)
	}
	a.Channel.ExhaustedUntil = time.Time{}
	a.Channel.RestUntil = time.Time{}
	if rankRouteTargets("drain", []routeTarget{a, b}, now, memory)[0].ID != "b" {
		t.Fatal("recovered earlier account reclaimed drain anchor")
	}
	memory = &routeMemory{Weights: map[string]int64{}}
	model.Strategy = "rotate"
	_ = state.reserve(model, []routeTarget{a, b}, a, memory, true, nil, now)
	if rankRouteTargets("rotate", []routeTarget{a, b}, now, memory)[0].ID != "b" {
		t.Fatal("rotation")
	}
	a.Weight = 3
	a2 := a
	a2.ID = "a2"
	a2.Quota.Reset = now.Add(2 * time.Hour)
	targets := []routeTarget{a, a2, b}
	model.Strategy = "weight"
	memory = &routeMemory{Weights: map[string]int64{}}
	counts := map[string]int{}
	history := []string{}
	for index := 0; index < 8; index++ {
		first := rankRouteTargets("weight", targets, now, memory)[0]
		counts[first.Member]++
		history = append(history, first.Member)
		if err := state.reserve(model, targets, first, memory, true, nil, now); err != nil {
			t.Fatal(err)
		}
	}
	if counts["a"] != 6 || counts["b"] != 2 || history[3] != "a" {
		t.Fatalf("weighted interleaving, grouped accounts: %v %v", counts, history)
	}
	a.Channel.RestUntil = now.Add(time.Hour)
	a2.Channel.RestUntil = now.Add(time.Hour)
	if rankRouteTargets("weight", []routeTarget{a, a2, b}, now, memory)[0].ID != "b" {
		t.Fatal("resting member stayed in cycle")
	}
}
func TestRoutingFastExplorationCheapAndRetryAfter(t *testing.T) {
	now := time.Now()
	a, b, c := routeFixture("a", 100, now), routeFixture("b", 100, now), routeFixture("c", 100, now)
	a.Channel = routeChannel{FirstToken: 500, Speed: 50, Measured: now}
	b.Channel = routeChannel{FirstToken: 480, Speed: 52, Measured: now}
	c.Channel = routeChannel{FirstToken: 1500, Speed: 15, Measured: now.Add(-2 * time.Hour)}
	memory := &routeMemory{Weights: map[string]int64{}}
	if rankRouteTargets("fast", []routeTarget{a, b, c}, now, memory)[0].ID != "a" {
		t.Fatal("sub-10% speed changes reordered")
	}
	memory.Turn = 4
	if rankRouteTargets("fast", []routeTarget{a, b, c}, now, memory)[0].ID != "c" {
		t.Fatal("stale channel was not probed")
	}
	c.Channel.RestUntil = now.Add(time.Hour)
	if rankRouteTargets("fast", []routeTarget{a, b, c}, now, memory)[0].ID == "c" {
		t.Fatal("probed resting channel")
	}
	a.Price, b.Price = routeNumber(2), routeNumber(1)
	if rankRouteTargets("cheap", []routeTarget{a, b, c}, now, memory)[0].ID != "b" {
		t.Fatal("effective price order")
	}
	a.Price = b.Price
	if rankRouteTargets("cheap", []routeTarget{a, b, c}, now, memory)[0].ID != "a" {
		t.Fatal("equal prices not stable")
	}
	if retryDelay("120", now) != 2*time.Minute || retryDelay("invalid", now) != 0 {
		t.Fatal("retry delay")
	}
	if sourcePriceMultiplier(SourcePricing{TimeRule: "deepseek"}, "deepseek-v4", time.Date(2026, 11, 12, 1, 0, 0, 0, time.UTC)) != 2 || sourcePriceMultiplier(SourcePricing{TimeRule: "deepseek"}, "deepseek-v4", time.Date(2026, 11, 12, 4, 0, 0, 0, time.UTC)) != 1 || sourcePriceMultiplier(SourcePricing{TimeRule: "ollama-deepseek"}, "deepseek-v4", time.Date(2026, 11, 14, 13, 0, 0, 0, time.UTC)) != .5 {
		t.Fatal("time price boundaries")
	}
}

func TestRoutingQuotaUsesWindowResetAndExpiringCreditBatches(t *testing.T) {
	now := time.Now().UTC()
	weekly := now.Add(72 * time.Hour)
	five := now.Add(2 * time.Hour)
	quota := modelplugins.Quota{ObservedAt: now.UnixMilli(), Windows: []modelplugins.QuotaWindow{{Name: "Weekly", Used: routeNumber(50), Span: 7 * 86400, ResetsAt: weekly.Format(time.RFC3339)}, {Name: "5h", Used: routeNumber(25), Span: 18000, ResetsAt: five.Format(time.RFC3339)}}}
	snapshot := quotaForModel(quota, "m", now)
	if !snapshot.Known || !snapshot.Reset.Equal(weekly.Truncate(time.Second)) || snapshot.Remaining == nil || *snapshot.Remaining != 50 {
		t.Fatalf("window selection %+v", snapshot)
	}
	quota.Windows[1].Used = routeNumber(100)
	if value := quotaForModel(quota, "m", now); value.Remaining == nil || *value.Remaining != 0 {
		t.Fatal("depleted short window ignored")
	}
	expiry := now.Add(time.Hour).Truncate(time.Second)
	quota = modelplugins.Quota{ObservedAt: now.UnixMilli(), Resets: &modelplugins.QuotaResets{Until: weekly.Format(time.RFC3339)}, Windows: []modelplugins.QuotaWindow{{Balance: routeNumber(80)}, {Aside: true, RunsOut: 10, RunsOutAt: expiry.Format(time.RFC3339)}}}
	snapshot = quotaForModel(quota, "m", now)
	if snapshot.Reset.IsZero() || !firstExpiry(snapshot).Equal(expiry) {
		t.Fatal("monthly reset or expiring credit batch lost")
	}
	if !quotaDeadlinePassed(quota, expiry.Add(time.Second)) {
		t.Fatal("cached balance survived credit expiry")
	}
}

func TestWeightedModelsUseProviderAccountStrategy(t *testing.T) {
	now := time.Now()
	a, b := routeFixture("account-a", 100, now.Add(time.Hour)), routeFixture("account-b", 100, now.Add(2*time.Hour))
	a.Member, b.Member = "same-model", "same-model"
	a.Weight, b.Weight = 3, 3
	targets := []routeTarget{a, b}
	provider := providerRouteModel(ModelCandidate{"source", "native"}, "rotate")
	state := routingState{}
	providerMemory := state.memory(provider, nil)
	rootMemory := &routeMemory{Weights: map[string]int64{}}
	root := CatalogModel{ID: "group", Strategy: "weight"}
	history := []string{}
	for round := 0; round < 4; round++ {
		own := rankRouteTargets(provider.Strategy, targets, now, providerMemory)
		chosen := rankRouteTargets("weight", own, now, rootMemory)[0]
		history = append(history, chosen.ID)
		_ = state.reserve(provider, targets, chosen, providerMemory, true, nil, now)
		_ = state.reserve(root, targets, chosen, rootMemory, true, nil, now)
	}
	if history[0] != "account-a" || history[1] != "account-b" || history[2] != "account-a" || history[3] != "account-b" {
		t.Fatal(history)
	}
	if (SourcePricing{AccountStrategy: "cheap"}).validate() {
		t.Fatal("cheap was accepted outside a routing group")
	}
}
func TestConfirmedFreeRoutingDoesNotInheritUnknownOrPaidFallbackPrice(t *testing.T) {
	ledger := newLedger(t)
	config := testConfiguration(nil)
	configured := false
	config.Pricing.DefaultConfigured = &configured
	config.Pricing.Models = map[string]ModelPricing{}
	if err := ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	call, err := ledger.Admit("main", "free-native", "", "", CallAttribution{SourceID: "source", RouteID: "free-route", Free: true})
	if err != nil || call.PriceStatus != "priced" || call.Price != (ModelPricing{}) {
		t.Fatalf("free route became unpriced: %+v %v", call, err)
	}
	if err = ledger.Settle(call, &Usage{Input: 10, Output: 2}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	var cost int64
	if err = ledger.db.QueryRow(`SELECT cost_nano FROM gateway_calls WHERE id=?`, call.ID).Scan(&cost); err != nil || cost != 0 {
		t.Fatal("free usage not settled at zero", err)
	}
	config.Pricing.Models["free-route"] = ModelPricing{InputPerMillion: 3}
	if err = ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	explicit, err := ledger.Admit("main", "free-native", "", "", CallAttribution{SourceID: "source", RouteID: "free-route", Free: true})
	if err != nil || explicit.Price.InputPerMillion != 3 {
		t.Fatal("explicit exit price was lost")
	}
}
