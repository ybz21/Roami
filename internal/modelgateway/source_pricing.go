package modelgateway

import (
	"database/sql"
	"encoding/json"
	"errors"
	"math"
	"net/http"
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
	return (containsField([]string{"tokens", "free", "quota", "unknown"}, rule.Mode) || inherit && (rule.Mode == "inherit" || rule.Mode == "")) && validAmount(rule.Price.InputPerMillion) && validAmount(rule.Price.OutputPerMillion) && validAmount(rule.Price.CacheReadPerMillion)
}
func (p SourcePricing) validate() bool {
	if !containsField([]string{"", "smart", "order", "drain", "rotate", "usage", "pace", "fast"}, p.AccountStrategy) || !validPriceRule(p.Default, true) || len(p.Models) > 200 || math.IsNaN(p.Multiplier) || math.IsInf(p.Multiplier, 0) || p.Multiplier < 0 || p.Multiplier > 1000 || !containsField([]string{"", "deepseek", "ollama-deepseek"}, p.TimeRule) {
		return false
	}
	for model, rule := range p.Models {
		if model == "" || len(model) > 200 || strings.ContainsAny(model, "\r\n\x00") || !validPriceRule(rule, true) {
			return false
		}
	}
	return true
}
func (pc *PricingConfig) sourceRule(source, model string) (PriceRule, bool) {
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
func sourcePriceMultiplier(p SourcePricing, model string, now time.Time) float64 {
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
func (pc *PricingConfig) routePriceAt(source, model string, now time.Time) (ModelPricing, bool) {
	if pc == nil {
		return ModelPricing{}, false
	}
	price, known := ModelPricing{}, false
	if rule, ok := pc.sourceRule(source, model); ok {
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
		} else if p, ok := pc.lookup(model); ok {
			price, known = p, true
		} else {
			price = pc.Default
			known = pc.DefaultConfigured == nil || *pc.DefaultConfigured || pc.Default != (ModelPricing{})
		}
	}
	multiplier := sourcePriceMultiplier(pc.Sources[source], model, now)
	scaled := ModelPricing{price.InputPerMillion * multiplier, price.OutputPerMillion * multiplier, price.CacheReadPerMillion * multiplier}
	if !validAmount(scaled.InputPerMillion) || !validAmount(scaled.OutputPerMillion) || !validAmount(scaled.CacheReadPerMillion) {
		return ModelPricing{}, false
	}
	return scaled, known
}
func (pc *PricingConfig) exitPriceAt(requested, source, model string, now time.Time) (ModelPricing, bool) {
	if pc == nil {
		return ModelPricing{}, false
	}
	if p, ok := pc.lookup(requested); requested != "" && ok {
		return p, true
	}
	return pc.routePriceAt(source, model, now)
}
func (h *Handler) sourcePricingManagement(w http.ResponseWriter, r *http.Request) bool {
	const prefix = "/v1/model-gateway/settings/sources/"
	if !strings.HasPrefix(r.URL.Path, prefix) {
		return false
	}
	id := strings.TrimPrefix(r.URL.Path, prefix)
	if !catalogID.MatchString(id) || h.Catalog == nil {
		reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
		return true
	}
	h.Catalog.mu.Lock()
	exists := false
	for _, source := range h.Catalog.value.Sources {
		if source.ID == id {
			exists = true
		}
	}
	h.Catalog.mu.Unlock()
	if !exists {
		reject(w, 404, "MODEL_NOT_CONFIGURED")
		return true
	}
	if r.Method == "GET" {
		config, err := h.Ledger.Configuration()
		if err != nil {
			reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		} else {
			writeJSON(w, 200, map[string]any{"data": config.Pricing.Sources[id], "currency": config.Currency})
		}
		return true
	}
	if r.Method != "PUT" {
		reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	var policy SourcePricing
	if decodeBody(w, r, &policy) != nil || !policy.validate() {
		reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
		return true
	}
	err := h.Ledger.db.Tx(func(tx *sql.Tx) error {
		config, err := configuration(tx)
		if err != nil {
			return err
		}
		if config.Pricing.Sources == nil {
			config.Pricing.Sources = map[string]SourcePricing{}
		}
		config.Pricing.Sources[id] = policy
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
	if err != nil {
		reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
	} else {
		writeJSON(w, 200, map[string]any{"data": policy})
	}
	return true
}
