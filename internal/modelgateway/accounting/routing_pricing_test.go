package accounting

import (
	"testing"
	"time"
)

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

func TestSourceMultiplierCannotOverflowAccountingRates(t *testing.T) {
	pricing := PricingConfig{Sources: map[string]SourcePricing{"source": {Default: PriceRule{Mode: "tokens", Price: ModelPricing{InputPerMillion: 1000000}}, Multiplier: 1000}}}
	if _, known := pricing.RoutePriceAt("source", "model", time.Now()); known {
		t.Fatal("unsafe scaled price could overflow integer accounting")
	}
}
