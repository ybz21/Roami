package modelgateway

import (
	"math"
	"testing"
)

func TestLookup_ExactMatch(t *testing.T) {
	pc := &PricingConfig{
		Default: ModelPricing{InputPerMillion: 1, OutputPerMillion: 2},
		Models: map[string]ModelPricing{
			"gpt-4o": {InputPerMillion: 2.5, OutputPerMillion: 10},
		},
	}
	p := pc.Lookup("gpt-4o")
	if p.InputPerMillion != 2.5 {
		t.Errorf("expected 2.5, got %f", p.InputPerMillion)
	}
}

func TestLookup_PrefixMatch(t *testing.T) {
	pc := &PricingConfig{
		Default: ModelPricing{InputPerMillion: 0},
		Models: map[string]ModelPricing{
			"claude-sonnet-4": {InputPerMillion: 3, OutputPerMillion: 15},
		},
	}
	p := pc.Lookup("claude-sonnet-4-20250514")
	if p.InputPerMillion != 3 {
		t.Errorf("prefix match failed: expected 3, got %f", p.InputPerMillion)
	}
}

func TestLookup_FallbackDefault(t *testing.T) {
	pc := &PricingConfig{
		Default: ModelPricing{InputPerMillion: 0.5},
		Models:  map[string]ModelPricing{},
	}
	p := pc.Lookup("unknown-model")
	if p.InputPerMillion != 0.5 {
		t.Errorf("expected default 0.5, got %f", p.InputPerMillion)
	}
}

func TestLookup_Nil(t *testing.T) {
	var pc *PricingConfig
	p := pc.Lookup("any")
	if p.InputPerMillion != 0 {
		t.Errorf("nil config should return zero pricing")
	}
}

func TestCalcCost(t *testing.T) {
	pc := &PricingConfig{
		Default: ModelPricing{},
		Models: map[string]ModelPricing{
			"gpt-4o": {InputPerMillion: 2.5, OutputPerMillion: 10, CacheReadPerMillion: 1.25},
		},
	}
	// 1M input + 100k output + 500k cache
	cost := pc.CalcCost("gpt-4o", 1_000_000, 100_000, 500_000)
	expected := 2.5 + 1.0 + 0.625 // = 4.125
	if math.Abs(cost-expected) > 0.001 {
		t.Errorf("expected %.3f, got %.3f", expected, cost)
	}
}

func TestCalcCost_Nil(t *testing.T) {
	var pc *PricingConfig
	cost := pc.CalcCost("any", 1000, 1000, 0)
	if cost != 0 {
		t.Errorf("nil config should return 0 cost")
	}
}

// Exit-based pricing: an aggregated model is billed at its public-name price
// regardless of which source/native served it; falls back to source/native when
// the exit name has no configured price.
func TestCalcCostExit(t *testing.T) {
	pc := &PricingConfig{
		Default: ModelPricing{InputPerMillion: 99}, // sentinel: should never be hit here
		Models: map[string]ModelPricing{
			"glm-5.2":                 {InputPerMillion: 2, OutputPerMillion: 8},
			"openrouter/z-ai/glm-4.6": {InputPerMillion: 5, OutputPerMillion: 5},
			"zai-org/GLM-4.6":         {InputPerMillion: 3, OutputPerMillion: 3},
		},
	}

	// Same exit model glm-5.2 → same price for either upstream/native.
	viaSilicon := pc.CalcCostExit("glm-5.2", "siliconflow", "zai-org/GLM-5.2", 1_000_000, 0, 0)
	viaOpenRouter := pc.CalcCostExit("glm-5.2", "openrouter", "z-ai/glm-5.2", 1_000_000, 0, 0)
	if viaSilicon != 2.0 || viaOpenRouter != 2.0 {
		t.Errorf("exit pricing not consistent: silicon=%.3f openrouter=%.3f want 2.0", viaSilicon, viaOpenRouter)
	}

	// Exit name unconfigured → fall back to source/model route price.
	route := pc.CalcCostExit("glm-4.6", "openrouter", "z-ai/glm-4.6", 1_000_000, 0, 0)
	if route != 5.0 {
		t.Errorf("route fallback = %.3f, want 5.0 (openrouter/z-ai/glm-4.6)", route)
	}
	// Exit + route both unconfigured → native model price.
	native := pc.CalcCostExit("glm-4.6", "siliconflow", "zai-org/GLM-4.6", 1_000_000, 0, 0)
	if native != 3.0 {
		t.Errorf("native fallback = %.3f, want 3.0 (zai-org/GLM-4.6)", native)
	}
}

func TestLookupExit_Nil(t *testing.T) {
	var pc *PricingConfig
	if pc.CalcCostExit("a", "s", "n", 1000, 1000, 0) != 0 {
		t.Error("nil config should return 0")
	}
}
