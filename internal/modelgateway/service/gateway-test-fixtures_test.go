package service

import (
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func newLedger(t *testing.T) *gatewayState {
	t.Helper()
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	l, err := openState(paths)
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

type Configuration = accounting.Configuration
type Call = accounting.Call
type CallAttribution = accounting.CallAttribution
type ModelPricing = accounting.ModelPricing
type PricingConfig = accounting.PricingConfig
type PriceRule = accounting.PriceRule
type SourcePricing = accounting.SourcePricing
type EffectiveSourcePrice = accounting.EffectiveSourcePrice
type Usage = accounting.Usage

func defaultConfiguration() Configuration              { return accounting.DefaultConfiguration() }
func routingPriceRevision(config Configuration) string { return accounting.PricingRevision(config) }

type Statistics = accounting.Statistics
