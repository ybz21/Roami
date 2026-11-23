package modelgateway

import (
	"net/http"

	"github.com/ybz21/Roami/internal/modelgateway/lan"
)

func (h *Handler) serveGatewayLAN(w http.ResponseWriter, r *http.Request) {
	if !lan.IsPrivatePeer(r.RemoteAddr) {
		reject(w, http.StatusForbidden, "MODEL_GATEWAY_LAN_ONLY")
		return
	}
	h.servePublicModels(w, r, true)
}

func (h *Handler) gatewayNetworkManagement(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path != "/v1/model-gateway/network" {
		return false
	}
	if h.Catalog == nil {
		reject(w, http.StatusServiceUnavailable, "MODEL_GATEWAY_UNAVAILABLE")
		return true
	}
	var view networkView
	switch r.Method {
	case http.MethodGet:
		view = h.network.view(h.Catalog)
	case http.MethodPut:
		var input struct {
			Enabled *bool `json:"enabled"`
		}
		if decodeBody(w, r, &input) != nil || input.Enabled == nil {
			reject(w, http.StatusBadRequest, "INVALID_MODEL_CATALOG")
			return true
		}
		var err error
		view, err = h.network.setEnabled(h.Catalog, http.HandlerFunc(h.serveGatewayLAN), *input.Enabled)
		if err != nil {
			reject(w, http.StatusServiceUnavailable, err.Error())
			return true
		}
	default:
		reject(w, http.StatusMethodNotAllowed, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": view})
	return true
}
