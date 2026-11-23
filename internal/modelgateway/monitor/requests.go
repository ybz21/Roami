package monitor

import (
	"net/http"
	"slices"
	"strings"
)

type RequestTotals struct {
	Requests       int `json:"requests"`
	Failed         int `json:"failed"`
	Recovered      int `json:"recovered"`
	Uncertain      int `json:"uncertain"`
	SameSource     int `json:"sameSource"`
	CrossSource    int `json:"crossSource"`
	SwitchedFailed int `json:"switchedFailed"`
}

func (t *RequestTotals) add(row Record) {
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

type RequestBucket struct {
	From   int64         `json:"from"`
	To     int64         `json:"to"`
	Totals RequestTotals `json:"totals"`
}

var requestFailureReasons = []string{"blocked", "exhausted", "interrupted", "upstreamLimited", "upstreamUnauthorized", "upstreamTimeout", "connectFailed", "dailyLimit", "quota", "failed"}

func requestOutcomeKey(row Record) string {
	if row.Outcome == "cancelled" || row.Outcome == "unknown" {
		return "uncertain"
	}
	return row.Outcome
}

func FailureReason(row Record) string {
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

type RouteObservation struct {
	RequestTotals
	Latest       *Record `json:"latest,omitempty"`
	LatestSwitch *Record `json:"latestSwitch,omitempty"`
}

func ObserveRoute(rows []Record, routeIDs []string, from int64) RouteObservation {
	result := RouteObservation{}
	for _, row := range rows {
		if row.Outcome == "" || row.At <= from || !slices.Contains(routeIDs, row.RouteID) {
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

func ValidFailureReason(reason string) bool {
	return slices.Contains(requestFailureReasons, reason)
}

func FindRequest(rows []Record, id string) (*Record, []Record) {
	attempts := []Record{}
	var terminal *Record
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
	return terminal, attempts
}

func RequestBuckets(start, span int64) []RequestBucket {
	points := make([]RequestBucket, 6)
	for index := range points {
		points[index].From = start + int64(index)*span
		points[index].To = points[index].From + span
	}
	return points
}

func RequestReport(rows []Record, storage map[string]any, points []RequestBucket, filter RequestFilter) map[string]any {
	start, end := points[0].From, points[len(points)-1].To
	span := points[0].To - start
	var totals RequestTotals
	routes, callers, outcomes := map[string]string{}, map[string]bool{}, map[string]int{}
	failureReasons := map[string]int{}
	recent := []Record{}
	for index := len(rows) - 1; index >= 0; index-- {
		row := rows[index]
		if row.Outcome == "" {
			continue
		}
		if _, known := routes[row.RouteID]; !known {
			routes[row.RouteID] = row.Model
		}
		callers[row.Caller] = true
		if (len(filter.RouteIDs) != 0 && !slices.Contains(filter.RouteIDs, row.RouteID)) || (filter.Caller != "" && filter.Caller != row.Caller) {
			continue
		}
		if row.At > start && row.At <= end {
			totals.add(row)
			points[(row.At-start-1)/span].Totals.add(row)
		}
		if row.At > filter.From && row.At <= filter.To {
			key := requestOutcomeKey(row)
			outcomes[key]++
			failure := FailureReason(row)
			if failure != "" {
				failureReasons[failure]++
			}
			if len(recent) < 50 && (filter.Outcome == "" || key == filter.Outcome) && (filter.Reason == "" || failure == filter.Reason) && matchesRequestSwitch(row, filter.Switched, failure) {
				recent = append(recent, row)
			}
		}
	}
	return map[string]any{
		"now": end, "totals": totals, "points": points, "routes": routes, "callers": callers, "outcomes": outcomes,
		"failureReasons": failureReasons, "recent": recent, "storage": storage,
	}
}

func matchesRequestSwitch(row Record, switched, failure string) bool {
	return switched == "" || row.Switch != "" && (switched == "any" || failure != "")
}
