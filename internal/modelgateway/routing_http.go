package modelgateway

import (
	"net/http"
	"time"
)

func (h *Handler) routingView(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" || h.Catalog == nil {
		reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return
	}
	id := r.URL.Query().Get("model")
	if !catalogID.MatchString(id) {
		reject(w, 400, "INVALID_MODEL_CATALOG")
		return
	}
	h.Catalog.mu.Lock()
	catalog := h.Catalog.snapshot()
	h.Catalog.mu.Unlock()
	var model *CatalogModel
	for _, value := range catalog.Models {
		if value.ID == id {
			copy := value
			model = &copy
			break
		}
	}
	if model == nil || !model.Aggregate {
		reject(w, 404, "MODEL_NOT_CONFIGURED")
		return
	}
	choice, err := h.newRoutingChoice(r.Context(), catalog, *model)
	if err != nil {
		reject(w, 503, "MODEL_ROUTE_UNAVAILABLE")
		return
	}
	h.routing.mu.Lock()
	defer h.routing.mu.Unlock()
	memory := h.routing.memory(choice.model, h.Ledger)
	now := h.Ledger.now()
	rows := []map[string]any{}
	available := 0
	for _, target := range rankRouteTargets(model.Strategy, choice.targets, now, memory) {
		node := choice.nodes[target.ID]
		ready := availableTarget(target, now)
		if ready {
			available++
		}
		source, native, account := groupSource, "", ""
		if node.leaf != nil {
			source, native, account = node.leaf.Candidate.SourceID, node.leaf.Candidate.Model, node.leaf.Account
		} else {
			native = node.child.model.ID
		}
		var reset, expiry *int64
		if !target.Quota.Reset.IsZero() {
			value := target.Quota.Reset.UnixMilli()
			reset = &value
		}
		if at := firstExpiry(target.Quota); !at.IsZero() {
			value := at.UnixMilli()
			expiry = &value
		}
		var rest *int64
		if target.Channel.RestUntil.After(now) {
			value := target.Channel.RestUntil.UnixMilli()
			rest = &value
		}
		rows = append(rows, map[string]any{"sourceId": source, "model": native, "account": routingAccountKey(account), "kind": target.Kind, "ready": ready, "remaining": target.Quota.Remaining, "resetAt": reset, "expiresAt": expiry, "restUntil": rest, "measuredAt": func() any {
			if target.Channel.Measured.IsZero() {
				return nil
			}
			return target.Channel.Measured.UnixMilli()
		}(), "recentTokens": target.Channel.Input + target.Channel.Output})
	}
	writeJSON(w, 200, map[string]any{"data": map[string]any{"now": time.Now().UnixMilli(), "available": available, "channels": rows}})
}
