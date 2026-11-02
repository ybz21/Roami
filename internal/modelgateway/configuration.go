package modelgateway

import (
	"encoding/json"
	"fmt"
	"math"
	"math/big"
	"regexp"
	"strconv"
	"time"
)

type Configuration struct {
	Currency   string        `json:"currency"`
	Timezone   string        `json:"timezone"`
	DailyLimit *float64      `json:"dailyLimit"`
	Pricing    PricingConfig `json:"pricing"`
}

func defaultConfiguration() Configuration {
	configured := false
	return Configuration{Currency: "CNY", Timezone: "UTC", Pricing: PricingConfig{DefaultConfigured: &configured, Models: map[string]ModelPricing{}}}
}

var currencyPattern = regexp.MustCompile(`^[A-Z]{3}$`)

func validAmount(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0) && value >= 0 && value <= 1_000_000
}

func (c Configuration) validate() error {
	if !currencyPattern.MatchString(c.Currency) || len(c.Timezone) > 100 || c.Timezone == "" || len(c.Pricing.Models) > 200 {
		return fmt.Errorf("INVALID_MODEL_PROXY_CONFIG")
	}
	if _, err := time.LoadLocation(c.Timezone); err != nil {
		return fmt.Errorf("INVALID_MODEL_PROXY_CONFIG")
	}
	if c.DailyLimit != nil && !validAmount(*c.DailyLimit) {
		return fmt.Errorf("INVALID_MODEL_PROXY_CONFIG")
	}
	prices := []ModelPricing{c.Pricing.Default}
	for name, price := range c.Pricing.Models {
		if len(name) == 0 || len(name) > 200 {
			return fmt.Errorf("INVALID_MODEL_PROXY_CONFIG")
		}
		prices = append(prices, price)
	}
	for _, price := range prices {
		if !validAmount(price.InputPerMillion) || !validAmount(price.OutputPerMillion) || !validAmount(price.CacheReadPerMillion) {
			return fmt.Errorf("INVALID_MODEL_PROXY_CONFIG")
		}
	}
	return nil
}

// Persist integer nanounits; only the imported pricing interface uses floats.
func decimal(value float64) *big.Rat {
	r, _ := new(big.Rat).SetString(strconv.FormatFloat(value, 'f', -1, 64))
	return r
}

func rounded(r *big.Rat) int64 {
	n := new(big.Int).Mul(r.Num(), big.NewInt(2))
	n.Add(n, r.Denom())
	return n.Quo(n, new(big.Int).Mul(r.Denom(), big.NewInt(2))).Int64()
}

func nanoAmount(value float64) int64 {
	return rounded(new(big.Rat).Mul(decimal(value), big.NewRat(1_000_000_000, 1)))
}

func costNano(price ModelPricing, usage Usage) int64 {
	total := new(big.Rat)
	for _, item := range []struct {
		count int64
		rate  float64
	}{
		{usage.Input - usage.Cached, price.InputPerMillion}, {usage.Output, price.OutputPerMillion}, {usage.Cached, price.CacheReadPerMillion},
	} {
		total.Add(total, new(big.Rat).Mul(decimal(item.rate), big.NewRat(item.count*1000, 1)))
	}
	return rounded(total)
}

func money(nano int64) string {
	return new(big.Rat).SetFrac(big.NewInt(nano), big.NewInt(1_000_000_000)).FloatString(9)
}

func decodeConfiguration(raw []byte) (Configuration, error) {
	c := defaultConfiguration()
	c.Pricing.DefaultConfigured = nil // Legacy saved defaults were explicit, including zero.
	err := json.Unmarshal(raw, &c)
	if err == nil {
		err = c.validate()
	}
	return c, err
}
