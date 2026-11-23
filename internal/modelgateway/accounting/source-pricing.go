package accounting

import (
	"database/sql"
	"encoding/json"
	"errors"
	"math"
	"slices"
	"strings"
	"time"
)

type PriceRule struct {
	Mode      string       `json:"mode"`
	Confirmed bool         `json:"confirmed,omitempty"`
	Price     ModelPricing `json:"price"`
}
type SourcePricing struct {
	AccountStrategy string               `json:"accountStrategy,omitempty"`
	Default         PriceRule            `json:"default"`
	Models          map[string]PriceRule `json:"models,omitempty"`
	Multiplier      float64              `json:"multiplier,omitempty"`
	TimeRule        string               `json:"timeRule,omitempty"`
}

func validPriceRule(rule PriceRule, inherit bool) bool {
	return (slices.Contains([]string{"tokens", "free", "quota", "unknown"}, rule.Mode) || inherit && (rule.Mode == "inherit" || rule.Mode == "")) && ValidAmount(rule.Price.InputPerMillion) && ValidAmount(rule.Price.OutputPerMillion) && ValidAmount(rule.Price.CacheReadPerMillion)
}
func (p SourcePricing) Valid() bool {
	if !slices.Contains([]string{"", "smart", "order", "drain", "rotate", "usage", "pace", "fast"}, p.AccountStrategy) || !validPriceRule(p.Default, true) || len(p.Models) > 200 || math.IsNaN(p.Multiplier) || math.IsInf(p.Multiplier, 0) || p.Multiplier < 0 || p.Multiplier > 1000 || !slices.Contains([]string{"", "deepseek", "ollama-deepseek"}, p.TimeRule) {
		return false
	}
	for model, rule := range p.Models {
		if model == "" || len(model) > 200 || strings.ContainsAny(model, "\r\n\x00") || !validPriceRule(rule, true) {
			return false
		}
	}
	return true
}
func (pc *PricingConfig) SourceRule(source, model string) (PriceRule, bool) {
	if pc == nil {
		return PriceRule{}, false
	}
	p, ok := pc.Sources[source]
	if !ok {
		return PriceRule{}, false
	}
	if rule, ok := p.Models[model]; ok && rule.Mode != "" && rule.Mode != "inherit" {
		return rule, true
	}
	if p.Default.Mode != "" && p.Default.Mode != "inherit" {
		return p.Default, true
	}
	return PriceRule{}, false
}
func SourcePriceMultiplier(p SourcePricing, model string, now time.Time) float64 {
	multiplier := p.Multiplier
	if multiplier == 0 {
		multiplier = 1
	}
	// Time pricing is explicit source configuration, never inferred from an endpoint.
	if !strings.Contains(strings.ToLower(model), "deepseek") {
		return multiplier
	}
	utc := now.UTC()
	weekday := utc.Weekday() != time.Saturday && utc.Weekday() != time.Sunday
	hour := utc.Hour()
	if p.TimeRule == "deepseek" && weekday && (hour >= 1 && hour < 4 || hour >= 6 && hour < 10) {
		multiplier *= 2
	}
	if p.TimeRule == "ollama-deepseek" && !(weekday && hour >= 12 && hour < 18) {
		multiplier *= .5
	}
	return multiplier
}
func (pc *PricingConfig) RoutePriceAt(source, model string, now time.Time) (ModelPricing, bool) {
	if pc == nil {
		return ModelPricing{}, false
	}
	price, known := ModelPricing{}, false
	if rule, ok := pc.SourceRule(source, model); ok {
		switch rule.Mode {
		case "tokens":
			price, known = rule.Price, true
		case "free":
			if !rule.Confirmed {
				return ModelPricing{}, false
			}
			price, known = ModelPricing{}, true
		case "quota":
			price, known = ModelPricing{}, true
		default:
			return ModelPricing{}, false
		}
	}
	if !known {
		if p, ok := pc.Models[source+"/"+model]; source != "" && ok {
			price, known = p, true
		} else if p, ok := pc.MatchingPrice(model); ok {
			price, known = p, true
		} else {
			price = pc.Default
			known = pc.DefaultConfigured == nil || *pc.DefaultConfigured || pc.Default != (ModelPricing{})
		}
	}
	multiplier := SourcePriceMultiplier(pc.Sources[source], model, now)
	scaled := ModelPricing{price.InputPerMillion * multiplier, price.OutputPerMillion * multiplier, price.CacheReadPerMillion * multiplier}
	if !ValidAmount(scaled.InputPerMillion) || !ValidAmount(scaled.OutputPerMillion) || !ValidAmount(scaled.CacheReadPerMillion) {
		return ModelPricing{}, false
	}
	return scaled, known
}
func (pc *PricingConfig) ExitPriceAt(requested, source, model string, now time.Time) (ModelPricing, bool) {
	if pc == nil {
		return ModelPricing{}, false
	}
	if p, ok := pc.MatchingPrice(requested); requested != "" && ok {
		return p, true
	}
	return pc.RoutePriceAt(source, model, now)
}

type EffectiveSourcePrice struct {
	Model      string                 `json:"model"`
	Origin     string                 `json:"origin"`
	Rule       PriceRule              `json:"rule"`
	Price      ModelPricing           `json:"price"`
	Known      bool                   `json:"known"`
	Multiplier float64                `json:"multiplier"`
	Exits      []EffectiveSourcePrice `json:"exits,omitempty"`
}

func (pc *PricingConfig) EffectiveSourcePrice(source, model string, now time.Time) EffectiveSourcePrice {
	p := pc.Sources[source]
	rule := p.Models[model]
	origin := "model"
	if rule.Mode == "" || rule.Mode == "inherit" {
		rule = p.Default
		origin = "source"
	}
	if rule.Mode == "" || rule.Mode == "inherit" {
		origin = "global"
		rule = PriceRule{Mode: "tokens", Price: pc.Default}
		if price, ok := pc.Models[source+"/"+model]; model != "" && ok {
			rule.Price = price
			origin = "legacySource"
		} else if price, ok := pc.MatchingPrice(model); ok {
			rule.Price = price
			origin = "legacyModel"
		}
	}
	price, known := pc.RoutePriceAt(source, model, now)
	if !known && rule.Mode == "tokens" {
		rule.Mode = "unknown"
	}
	return EffectiveSourcePrice{Model: model, Origin: origin, Rule: rule, Price: price, Known: known, Multiplier: SourcePriceMultiplier(p, model, now)}
}
func (l *Ledger) SaveSourcePricing(id, scope, model string, policy SourcePricing) error {
	return l.db.Tx(func(tx *sql.Tx) error {
		config, err := configuration(tx)
		if err != nil {
			return err
		}
		if config.Pricing.Sources == nil {
			config.Pricing.Sources = map[string]SourcePricing{}
		}
		current := config.Pricing.Sources[id]
		switch scope {
		case "default":
			current.Default, current.Multiplier, current.TimeRule = policy.Default, policy.Multiplier, policy.TimeRule
		case "account":
			current.AccountStrategy = policy.AccountStrategy
		case "model":
			if current.Models == nil {
				current.Models = map[string]PriceRule{}
			}
			if rule, ok := policy.Models[model]; ok {
				current.Models[model] = rule
			} else {
				delete(current.Models, model)
			}
		default:
			current = policy
		}
		if !current.Valid() {
			return errors.New("INVALID_MODEL_PROXY_CONFIG")
		}
		config.Pricing.Sources[id] = current
		if len(config.Pricing.Sources) > 64 {
			return errors.New("INVALID_MODEL_PROXY_CONFIG")
		}
		raw, err := json.Marshal(config)
		if err != nil {
			return err
		}
		_, err = tx.Exec(`INSERT INTO gateway_configuration(id,value) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value`, string(raw))
		return err
	})
}

func PruneSourcePricing(tx *sql.Tx, sources map[string]bool) error {
	config, err := configuration(tx)
	if err != nil {
		return err
	}
	changed := false
	for id := range config.Pricing.Sources {
		if !sources[id] {
			delete(config.Pricing.Sources, id)
			changed = true
		}
	}
	if changed {
		raw, e := json.Marshal(config)
		if e != nil {
			return e
		}
		_, err = tx.Exec(`UPDATE gateway_configuration SET value=? WHERE id=1`, string(raw))
	}
	return err
}
