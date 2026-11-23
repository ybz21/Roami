package service

import (
	"net/http"
	"slices"
	"strings"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
)

func (h *Handler) sourcePricingManagement(w http.ResponseWriter, r *http.Request) bool {
	const prefix = "/v1/model-gateway/settings/sources/"
	if !strings.HasPrefix(r.URL.Path, prefix) {
		return false
	}
	id := strings.TrimPrefix(r.URL.Path, prefix)
	if !modelcatalog.ValidID(id) || h.Catalog == nil {
		httpapi.Reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
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
		httpapi.Reject(w, 404, "MODEL_NOT_CONFIGURED")
		return true
	}
	if r.Method == "GET" {
		response, err := h.sourcePricingResponse(id)
		if err != nil {
			httpapi.Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		} else {
			httpapi.WriteJSON(w, 200, response)
		}
		return true
	}
	if r.Method != "PUT" {
		httpapi.Reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	var policy accounting.SourcePricing
	if httpapi.DecodeJSON(w, r, &policy) != nil || !policy.Valid() {
		httpapi.Reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
		return true
	}
	scope, model := r.URL.Query().Get("scope"), r.URL.Query().Get("model")
	if !slices.Contains([]string{"", "default", "model", "account"}, scope) || scope == "model" && (model == "" || len(model) > 200) {
		httpapi.Reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
		return true
	}
	err := h.state.accounting.SaveSourcePricing(id, scope, model, policy)
	if err != nil {
		httpapi.Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
	} else {
		response, e := h.sourcePricingResponse(id)
		if e != nil {
			httpapi.Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		} else {
			httpapi.WriteJSON(w, 200, response)
		}
	}
	return true
}

func (h *Handler) sourcePricingResponse(id string) (map[string]any, error) {
	config, err := h.state.accounting.Configuration()
	if err != nil {
		return nil, err
	}
	now := h.state.now()
	effective := []accounting.EffectiveSourcePrice{}
	byName := map[string]int{}
	h.Catalog.mu.Lock()
	defer h.Catalog.mu.Unlock()
	for _, m := range h.Catalog.value.Models {
		for _, c := range m.Candidates {
			if c.SourceID != id {
				continue
			}
			index, ok := byName[c.Model]
			if !ok {
				index = len(effective)
				byName[c.Model] = index
				effective = append(effective, config.Pricing.EffectiveSourcePrice(id, c.Model, now))
			}
			if price, ok := config.Pricing.MatchingPrice(m.ID); ok {
				effective[index].Exits = append(effective[index].Exits, accounting.EffectiveSourcePrice{Model: m.ID, Origin: "exit", Rule: accounting.PriceRule{Mode: "tokens", Price: price}, Price: price, Known: true, Multiplier: 1})
			}
		}
	}
	return map[string]any{"data": config.Pricing.Sources[id], "currency": config.Currency, "effective": effective, "summary": config.Pricing.EffectiveSourcePrice(id, "", now), "now": now.UnixMilli()}, nil
}
