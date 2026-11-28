package service

import (
	"net/http"
	"time"

	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
	"github.com/ybz21/Roami/internal/modelgateway/routing"
)

func (h *Handler) routingView(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" || h.Catalog == nil {
		httpapi.Reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return
	}
	id := r.URL.Query().Get("model")
	if !modelcatalog.ValidID(id) {
		httpapi.Reject(w, 400, "INVALID_MODEL_CATALOG")
		return
	}
	h.Catalog.mu.Lock()
	catalog := h.Catalog.snapshot()
	h.Catalog.mu.Unlock()
	var model *CatalogModel
	for _, value := range catalog.Models {
		if value.MatchesGatewayName(id) {
			copy := value
			model = &copy
			break
		}
	}
	if model == nil || !model.Aggregate {
		httpapi.Reject(w, 404, "MODEL_NOT_CONFIGURED")
		return
	}
	choice, err := h.newRoutingChoice(r.Context(), catalog, *model, routing.Requirements{}, true)
	if err != nil {
		httpapi.Reject(w, 503, "MODEL_ROUTE_UNAVAILABLE")
		return
	}
	var observation *monitor.RouteObservation
	if h.Monitor != nil {
		if rows, _, readErr := h.Monitor.Snapshot(); readErr == nil {
			value := monitor.ObserveRoute(rows, append([]string{model.ID}, model.AdditionalGatewayNames()...), h.Monitor.Now().Add(-time.Hour).UnixMilli())
			observation = &value
		}
	}
	available, rows, members := choice.Inspect()
	httpapi.WriteJSON(w, 200, map[string]any{"data": map[string]any{"now": time.Now().UnixMilli(), "available": available, "channels": rows, "members": members, "observation": observation}})
}
