package modelgateway

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestSourcePricingScopedSaveAndEffectiveMetadata(t *testing.T) {
	h := aggregateFixture(t, responseFixture, responseFixture)
	config, _ := h.Ledger.Configuration()
	config.Pricing.Models["coding-main"] = ModelPricing{InputPerMillion: 99}
	config.Pricing.Sources["work"] = SourcePricing{Default: PriceRule{Mode: "tokens", Price: ModelPricing{InputPerMillion: 3}}, Multiplier: 2, AccountStrategy: "rotate"}
	if err := h.Ledger.Configure(config); err != nil {
		t.Fatal(err)
	}
	write := func(query, body string) {
		t.Helper()
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("PUT", "/v1/model-gateway/settings/sources/work?"+query, strings.NewReader(body)))
		if w.Code != 200 {
			t.Fatal(w.Code, w.Body.String())
		}
	}
	write("scope=model&model=fixture", `{"default":{"mode":"tokens","price":{"input_per_million":500}},"multiplier":5,"accountStrategy":"smart","models":{"fixture":{"mode":"tokens","price":{"input_per_million":7}}}}`)
	after, _ := h.Ledger.Configuration()
	p := after.Pricing.Sources["work"]
	if p.Default.Price.InputPerMillion != 3 || p.Multiplier != 2 || p.AccountStrategy != "rotate" || p.Models["fixture"].Price.InputPerMillion != 7 {
		t.Fatalf("model save included other drafts: %+v", p)
	}
	write("scope=default", `{"default":{"mode":"tokens","price":{"input_per_million":4}},"multiplier":3,"models":{"fixture":{"mode":"unknown"}}}`)
	write("scope=account", `{"accountStrategy":"drain","default":{"mode":"unknown"}}`)
	response, err := h.sourcePricingResponse("work")
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(response)
	var result struct {
		Data      SourcePricing          `json:"data"`
		Effective []EffectiveSourcePrice `json:"effective"`
	}
	if err = json.Unmarshal(raw, &result); err != nil {
		t.Fatal(err)
	}
	p = result.Data
	if p.Models["fixture"].Price.InputPerMillion != 7 || p.Default.Price.InputPerMillion != 4 || p.AccountStrategy != "drain" || len(result.Effective) != 1 {
		t.Fatalf("independent save: %s", raw)
	}
	e := result.Effective[0]
	if e.Origin != "model" || e.Multiplier != 3 || e.Price.InputPerMillion != 21 || len(e.Exits) != 1 || e.Exits[0].Price.InputPerMillion != 99 {
		t.Fatalf("effective metadata: %s", raw)
	}
	stale := config
	stale.Pricing.Default.InputPerMillion = 11
	if err = h.Ledger.configureScope(stale, "pricing"); err != nil {
		t.Fatal(err)
	}
	after, _ = h.Ledger.Configuration()
	if after.Pricing.Sources["work"].AccountStrategy != "drain" {
		t.Fatal("global save overwrote source")
	}
	limit := 15.0
	stale.DailyLimit = &limit
	if err = h.Ledger.configureScope(stale, "limits"); err != nil {
		t.Fatal(err)
	}
	after, _ = h.Ledger.Configuration()
	if after.Pricing.Default.InputPerMillion != 11 || after.DailyLimit == nil || *after.DailyLimit != 15 {
		t.Fatal("limit save overwrote pricing")
	}
}
