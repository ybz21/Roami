package modelgateway

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
)

func selectedCatalogModel(catalog ModelCatalog, id string) (CatalogModel, error) {
	for _, model := range catalog.Models {
		if model.ID == id || containsField(model.Aliases, id) {
			if !model.enabled() {
				return CatalogModel{}, errors.New("MODEL_ROUTE_DISABLED")
			}
			if !containsField([]string{"openai-completions", "openai-responses", "anthropic-messages"}, model.Protocol) {
				return CatalogModel{}, errors.New("INVALID_MODEL_PROTOCOL")
			}
			return model, nil
		}
	}
	return CatalogModel{}, errors.New("MODEL_NOT_CONFIGURED")
}
func (h *Handler) modelSelectionManagement(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path != "/v1/model-gateway/models/selection" {
		return false
	}
	if r.Method != "GET" {
		reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	if h.Catalog == nil {
		reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return true
	}
	role := r.URL.Query().Get("role")
	route, err := readNodeModels(h.Ledger.paths, role)
	if err != nil {
		reject(w, 400, "INVALID_MODEL_CONFIG")
		return true
	}
	s := h.Catalog
	s.mu.Lock()
	catalog := s.snapshot()
	disabled := catalog.AgentKeys["roami"].Disabled
	s.mu.Unlock()
	if disabled {
		reject(w, 403, "MODEL_GATEWAY_KEY_DISABLED")
		return true
	}
	id := strings.TrimSpace(r.URL.Query().Get("model"))
	if id == "auto" {
		if strings.TrimRight(route.endpoint, "/") != s.baseURL+"/v1" {
			reject(w, 409, "MODEL_ROLE_REQUIRES_BINDING")
			return true
		}
		id = route.model
	}
	model, err := selectedCatalogModel(catalog, id)
	if err != nil {
		reject(w, 400, err.Error())
		return true
	}
	freeOnly := r.URL.Query().Get("freeOnly") == "true" || model.FreeOnly
	writeJSON(w, 200, map[string]any{"data": map[string]any{"model": model.ID, "freeOnly": freeOnly, "revision": catalog.Revision, "routeId": route.identity()}})
	return true
}

// Selection is per request; the saved role remains the authority for generation parameters.
func (h *Handler) forwardSelected(w http.ResponseWriter, r *http.Request, body []byte, requested map[string]any, role string) {
	if h.Catalog == nil {
		reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return
	}
	s := h.Catalog
	s.mu.Lock()
	catalog := s.snapshot()
	s.mu.Unlock()
	model, err := selectedCatalogModel(catalog, r.Header.Get("X-Roami-Model-Selection"))
	if err != nil {
		reject(w, 400, err.Error())
		return
	}
	if requested["model"] != model.ID {
		reject(w, 409, "MODEL_GATEWAY_ROUTE_CHANGED")
		return
	}
	check := func() error {
		route, err := readNodeModels(h.Ledger.paths, role)
		if err != nil {
			return err
		}
		copy := map[string]any{}
		for key, value := range requested {
			copy[key] = value
		}
		copy["model"] = route.model
		if !route.accepts(copy, r.Header.Get("X-Roami-Model-Route")) || r.Header.Get("X-Roami-Model-Route") == "" {
			return errors.New("MODEL_GATEWAY_ROUTE_CHANGED")
		}
		s.mu.Lock()
		defer s.mu.Unlock()
		if s.value.AgentKeys["roami"].Disabled {
			return errors.New("MODEL_GATEWAY_KEY_DISABLED")
		}
		if s.value.Revision != r.Header.Get("X-Roami-Model-Revision") {
			return errors.New("MODEL_GATEWAY_ROUTE_CHANGED")
		}
		return nil
	}
	if err := check(); err != nil {
		reject(w, 409, err.Error())
		return
	}
	if r.Header.Get("X-Roami-Free-Only") == "true" {
		model.FreeOnly = true
		model.AllowPlan = false
	}
	if model.FreeOnly && !model.Aggregate {
		model.Aggregate = true
		model.Strategy = "order"
	}
	for index, row := range catalog.Models {
		if row.ID == model.ID {
			catalog.Models[index] = model
		}
	}
	r.Body = io.NopCloser(bytes.NewReader(body))
	r = r.WithContext(context.WithValue(r.Context(), gatewayKeyContext{}, keyID(catalog.AgentKeys["roami"].ID)))
	h.forwardCatalog(w, r, catalog, "roami_"+role, "openai-completions", check)
}
