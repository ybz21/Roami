package service

import (
	"net/http"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
)

func (h *Handler) requestRouteIDs(route string) []string {
	if route == "" {
		return nil
	}
	if h.Catalog != nil {
		h.Catalog.mu.Lock()
		defer h.Catalog.mu.Unlock()
		for _, model := range h.Catalog.value.Models {
			if model.Aggregate && model.ID == route {
				return append([]string{route}, model.AdditionalGatewayNames()...)
			}
		}
	}
	return []string{route}
}

func (h *Handler) requestMonitorManagement(w http.ResponseWriter, r *http.Request) bool {
	const path = "/v1/model-gateway/monitor"
	id, detail := strings.CutPrefix(r.URL.Path, path+"/requests/")
	query := r.URL.Query()
	view := query.Get("view")
	if !detail && !(r.URL.Path == path && (view == "requests" || view == "request-summary")) {
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
	route := query.Get("routeId")
	if route != "" && !modelcatalog.ValidID(route) {
		httpapi.Reject(w, 400, "INVALID_MONITOR_QUERY")
		return true
	}
	routeIDs := h.requestRouteIDs(route)
	if detail {
		parsed, err := uuid.Parse(id)
		if err != nil || parsed.String() != id {
			httpapi.Reject(w, 404, "MODEL_REQUEST_NOT_FOUND")
			return true
		}
	}
	rows, storage, err := h.Monitor.Snapshot()
	if err != nil {
		httpapi.Reject(w, 503, "MODEL_MONITOR_UNAVAILABLE")
		return true
	}
	if detail {
		terminal, attempts := monitor.FindRequest(rows, id)
		if terminal == nil || len(routeIDs) != 0 && !slices.Contains(routeIDs, terminal.RouteID) {
			httpapi.Reject(w, 404, "MODEL_REQUEST_NOT_FOUND")
			return true
		}
		httpapi.WriteJSON(w, 200, map[string]any{"data": map[string]any{
			"request": terminal, "attempts": h.requestAttemptsWithBilling(r.Context(), *terminal, attempts), "complete": len(attempts) == terminal.Attempts,
		}})
		return true
	}
	hours := 24
	if value := query.Get("hours"); value != "" {
		if !slices.Contains([]string{"1", "6", "24"}, value) {
			httpapi.Reject(w, 400, "INVALID_MONITOR_QUERY")
			return true
		}
		hours, _ = strconv.Atoi(value)
	}
	caller, outcome, reason, switched := query.Get("caller"), query.Get("outcome"), query.Get("reason"), query.Get("switch")
	if len(caller) > 120 || switched != "" && !slices.Contains([]string{"any", "failed"}, switched) ||
		outcome != "" && !slices.Contains([]string{"success", "recovered", "blocked", "exhausted", "interrupted", "failed", "uncertain"}, outcome) ||
		reason != "" && !monitor.ValidFailureReason(reason) {
		httpapi.Reject(w, 400, "INVALID_MONITOR_QUERY")
		return true
	}
	now := h.Monitor.Now().UnixMilli()
	span := (time.Duration(hours) * time.Hour / 6).Milliseconds()
	end := now
	if value := query.Get("end"); value != "" {
		var err error
		end, err = strconv.ParseInt(value, 10, 64)
		if err != nil || end < 1 || end > now {
			httpapi.Reject(w, 400, "INVALID_MONITOR_QUERY")
			return true
		}
	}
	start := end - span*6
	sampleFrom, sampleTo := start, end
	if query.Has("from") || query.Has("to") {
		var errFrom, errTo error
		sampleFrom, errFrom = strconv.ParseInt(query.Get("from"), 10, 64)
		sampleTo, errTo = strconv.ParseInt(query.Get("to"), 10, 64)
		if errFrom != nil || errTo != nil || sampleFrom >= sampleTo || sampleTo > end || sampleFrom < start {
			httpapi.Reject(w, 400, "INVALID_MONITOR_QUERY")
			return true
		}
	}
	filter := monitor.RequestFilter{From: sampleFrom, To: sampleTo, RouteIDs: routeIDs,
		Caller: caller, Outcome: outcome, Reason: reason, Switched: switched}
	points := monitor.RequestBuckets(start, span)
	if view == "request-summary" {
		httpapi.WriteJSON(w, 200, map[string]any{"data": monitor.SummarizeRequests(rows, points, filter)})
		return true
	}
	httpapi.WriteJSON(w, 200, map[string]any{"data": monitor.RequestReport(rows, storage, points, filter)})
	return true
}
