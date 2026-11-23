package service

import (
	"net/http"
	"slices"
	"strconv"

	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
)

func (h *Handler) monitorManagement(w http.ResponseWriter, r *http.Request) bool {
	if h.requestMonitorManagement(w, r) {
		return true
	}
	if r.URL.Path == "/v1/model-gateway/monitor/check" {
		h.runQualityProbe(w, r)
		return true
	}
	if r.URL.Path != "/v1/model-gateway/monitor" {
		return false
	}
	if r.Method != "GET" {
		httpapi.Reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	if h.Monitor == nil {
		httpapi.Reject(w, 503, "MODEL_MONITOR_UNAVAILABLE")
		return true
	}
	hours := 24
	if text := r.URL.Query().Get("hours"); text != "" {
		value, err := strconv.Atoi(text)
		if err != nil || !slices.Contains([]string{"1", "6", "24"}, text) {
			httpapi.Reject(w, 400, "INVALID_MONITOR_QUERY")
			return true
		}
		hours = value
	}
	source, model := r.URL.Query().Get("sourceId"), r.URL.Query().Get("model")
	if len(source) > 160 || len(model) > 200 {
		httpapi.Reject(w, 400, "INVALID_MONITOR_QUERY")
		return true
	}
	all, storage, err := h.Monitor.Snapshot()
	if err != nil {
		httpapi.Reject(w, 503, "MODEL_MONITOR_UNAVAILABLE")
		return true
	}
	now := h.Monitor.Now()
	httpapi.WriteJSON(w, 200, map[string]any{"data": monitor.AttemptsReport(all, storage, now, hours, source, model)})
	return true
}
