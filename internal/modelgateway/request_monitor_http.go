package modelgateway

import (
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

type requestTotals struct {
	Requests       int `json:"requests"`
	Failed         int `json:"failed"`
	Recovered      int `json:"recovered"`
	Uncertain      int `json:"uncertain"`
	SameSource     int `json:"sameSource"`
	CrossSource    int `json:"crossSource"`
	SwitchedFailed int `json:"switchedFailed"`
}

func (t *requestTotals) add(row MonitorRecord) {
	t.Requests++
	switch row.Outcome {
	case "recovered":
		t.Recovered++
	case "unknown", "cancelled":
		t.Uncertain++
	case "success":
	default:
		t.Failed++
		if row.Switch != "" {
			t.SwitchedFailed++
		}
	}
	switch row.Switch {
	case "source":
		t.CrossSource++
	case "model":
		t.SameSource++
	}
}

func (h *Handler) requestRouteIDs(route string) []string {
	if route == "" {
		return nil
	}
	if h.Catalog != nil {
		h.Catalog.mu.Lock()
		defer h.Catalog.mu.Unlock()
		for _, model := range h.Catalog.value.Models {
			if model.Aggregate && model.ID == route {
				return append([]string{route}, model.additionalGatewayNames()...)
			}
		}
	}
	return []string{route}
}

type requestBucket struct {
	From   int64         `json:"from"`
	To     int64         `json:"to"`
	Totals requestTotals `json:"totals"`
}

var requestFailureReasons = []string{"blocked", "exhausted", "interrupted", "upstreamLimited", "upstreamUnauthorized", "upstreamTimeout", "connectFailed", "dailyLimit", "quota", "failed"}

func requestOutcomeKey(row MonitorRecord) string {
	if row.Outcome == "cancelled" || row.Outcome == "unknown" {
		return "uncertain"
	}
	return row.Outcome
}

func requestFailureReason(row MonitorRecord) string {
	switch row.Outcome {
	case "success", "recovered", "unknown", "cancelled":
		return ""
	case "blocked", "exhausted", "interrupted":
		return row.Outcome
	}
	switch row.Error {
	case "MODEL_PROXY_DAILY_LIMIT":
		return "dailyLimit"
	case "MODEL_TRANSPORT_FAILED":
		return "connectFailed"
	}
	if row.Attempts > 0 && (row.Error == "" || strings.HasPrefix(row.Error, "MODEL_HTTP_")) {
		switch row.Status {
		case http.StatusTooManyRequests:
			return "upstreamLimited"
		case http.StatusUnauthorized, http.StatusForbidden:
			return "upstreamUnauthorized"
		case http.StatusRequestTimeout, http.StatusGatewayTimeout:
			return "upstreamTimeout"
		case http.StatusPaymentRequired:
			return "quota"
		}
	}
	return "failed"
}

type requestObservationSummary struct {
	requestTotals
	Latest       *MonitorRecord `json:"latest,omitempty"`
	LatestSwitch *MonitorRecord `json:"latestSwitch,omitempty"`
}

func routeObservation(rows []MonitorRecord, routeIDs []string, from int64) requestObservationSummary {
	result := requestObservationSummary{}
	for _, row := range rows {
		if row.Outcome == "" || row.At <= from || !containsField(routeIDs, row.RouteID) {
			continue
		}
		result.add(row)
		if row.Attempts > 0 {
			copy := row
			result.Latest = &copy
		}
		if row.Switch != "" {
			copy := row
			result.LatestSwitch = &copy
		}
	}
	return result
}

func (h *Handler) requestMonitorManagement(w http.ResponseWriter, r *http.Request) bool {
	const monitor = "/v1/model-gateway/monitor"
	id, detail := strings.CutPrefix(r.URL.Path, monitor+"/requests/")
	query := r.URL.Query()
	view := query.Get("view")
	if !detail && !(r.URL.Path == monitor && (view == "requests" || view == "request-summary")) {
		return false
	}
	if r.Method != "GET" {
		reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	if h.Monitor == nil {
		reject(w, 503, "MODEL_MONITOR_UNAVAILABLE")
		return true
	}
	route := query.Get("routeId")
	if route != "" && !catalogID.MatchString(route) {
		reject(w, 400, "INVALID_MONITOR_QUERY")
		return true
	}
	routeIDs := h.requestRouteIDs(route)
	if detail {
		parsed, err := uuid.Parse(id)
		if err != nil || parsed.String() != id {
			reject(w, 404, "MODEL_REQUEST_NOT_FOUND")
			return true
		}
	}
	rows, storage, err := h.Monitor.Snapshot()
	if err != nil {
		reject(w, 503, "MODEL_MONITOR_UNAVAILABLE")
		return true
	}
	if detail {
		attempts := []MonitorRecord{}
		var terminal *MonitorRecord
		for _, row := range rows {
			if row.RequestID != id {
				continue
			}
			if row.Outcome == "" {
				attempts = append(attempts, row)
			} else {
				copy := row
				terminal = &copy
			}
		}
		if terminal == nil || len(routeIDs) != 0 && !containsField(routeIDs, terminal.RouteID) {
			reject(w, 404, "MODEL_REQUEST_NOT_FOUND")
			return true
		}
		writeJSON(w, 200, map[string]any{"data": map[string]any{
			"request": terminal, "attempts": h.requestAttemptsWithBilling(r.Context(), *terminal, attempts), "complete": len(attempts) == terminal.Attempts,
		}})
		return true
	}
	hours := 24
	if value := query.Get("hours"); value != "" {
		if !containsField([]string{"1", "6", "24"}, value) {
			reject(w, 400, "INVALID_MONITOR_QUERY")
			return true
		}
		hours, _ = strconv.Atoi(value)
	}
	caller, outcome, reason, switched := query.Get("caller"), query.Get("outcome"), query.Get("reason"), query.Get("switch")
	if len(caller) > 120 || switched != "" && !containsField([]string{"any", "failed"}, switched) ||
		outcome != "" && !containsField([]string{"success", "recovered", "blocked", "exhausted", "interrupted", "failed", "uncertain"}, outcome) ||
		reason != "" && !containsField(requestFailureReasons, reason) {
		reject(w, 400, "INVALID_MONITOR_QUERY")
		return true
	}
	now := h.Monitor.now().UnixMilli()
	span := (time.Duration(hours) * time.Hour / 6).Milliseconds()
	end := now
	if value := query.Get("end"); value != "" {
		var err error
		end, err = strconv.ParseInt(value, 10, 64)
		if err != nil || end < 1 || end > now {
			reject(w, 400, "INVALID_MONITOR_QUERY")
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
			reject(w, 400, "INVALID_MONITOR_QUERY")
			return true
		}
	}
	points := make([]requestBucket, 6)
	for index := range points {
		points[index].From = start + int64(index)*span
		points[index].To = points[index].From + span
	}
	if view == "request-summary" {
		data := summarizeRequests(rows, points, requestSummaryFilter{
			from: sampleFrom, to: sampleTo, routeIDs: routeIDs, caller: caller, outcome: outcome, reason: reason, switched: switched,
		})
		writeJSON(w, 200, map[string]any{"data": data})
		return true
	}
	var totals requestTotals
	routes, callers, outcomes := map[string]string{}, map[string]bool{}, map[string]int{}
	failureReasons := map[string]int{}
	recent := []MonitorRecord{}
	for index := len(rows) - 1; index >= 0; index-- {
		row := rows[index]
		if row.Outcome == "" {
			continue
		}
		if _, known := routes[row.RouteID]; !known {
			routes[row.RouteID] = row.Model
		}
		callers[row.Caller] = true
		if (len(routeIDs) != 0 && !containsField(routeIDs, row.RouteID)) || (caller != "" && caller != row.Caller) {
			continue
		}
		if row.At > start && row.At <= end {
			totals.add(row)
			points[(row.At-start-1)/span].Totals.add(row)
		}
		if row.At > sampleFrom && row.At <= sampleTo {
			key := requestOutcomeKey(row)
			outcomes[key]++
			failure := requestFailureReason(row)
			if failure != "" {
				failureReasons[failure]++
			}
			if len(recent) < 50 && (outcome == "" || key == outcome) && (reason == "" || failure == reason) && matchesRequestSwitch(row, switched, failure) {
				recent = append(recent, row)
			}
		}
	}
	writeJSON(w, 200, map[string]any{"data": map[string]any{
		"now": end, "totals": totals, "points": points, "routes": routes, "callers": callers, "outcomes": outcomes,
		"failureReasons": failureReasons, "recent": recent, "storage": storage,
	}})
	return true
}

func matchesRequestSwitch(row MonitorRecord, switched, failure string) bool {
	return switched == "" || row.Switch != "" && (switched == "any" || failure != "")
}
