package modelgateway

import (
	"math"
	"net/http"
	"sort"
	"strconv"
	"time"
)

type monitorTotals struct {
	Requests      int      `json:"requests"`
	Failed        int      `json:"failed"`
	Success       *float64 `json:"success"`
	FirstTokenP95 *float64 `json:"firstTokenP95"`
	OutputP50     *float64 `json:"outputP50"`
	Quality       *float64 `json:"quality"`
	Graded        int      `json:"graded"`
}

func quantile(values []float64, q float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	sort.Float64s(values)
	index := int(math.Ceil(float64(len(values))*q)) - 1
	if index >= len(values) {
		index = len(values) - 1
	}
	v := values[index]
	return &v
}
func summarizeMonitor(rows []MonitorRecord) monitorTotals {
	result := monitorTotals{Requests: len(rows)}
	var first, speed []float64
	passed := 0
	for _, row := range rows {
		if !row.Success {
			result.Failed++
		} else {
			if row.FirstToken != nil {
				first = append(first, *row.FirstToken)
			}
			if row.TokensPerSecond != nil {
				speed = append(speed, *row.TokensPerSecond)
			}
		}
		if row.Quality == "pass" || row.Quality == "fail" {
			result.Graded++
			if row.Quality == "pass" {
				passed++
			}
		}
	}
	if len(rows) > 0 {
		success := float64(len(rows)-result.Failed) / float64(len(rows))
		result.Success = &success
	}
	if result.Graded > 0 {
		quality := float64(passed) / float64(result.Graded)
		result.Quality = &quality
	}
	result.FirstTokenP95 = quantile(first, .95)
	result.OutputP50 = quantile(speed, .5)
	return result
}
func (h *Handler) monitorManagement(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path == "/v1/model-gateway/monitor/check" {
		h.runQualityProbe(w, r)
		return true
	}
	if r.URL.Path != "/v1/model-gateway/monitor" {
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
	hours := 24
	if text := r.URL.Query().Get("hours"); text != "" {
		value, err := strconv.Atoi(text)
		if err != nil || !containsField([]string{"1", "6", "24"}, text) {
			reject(w, 400, "INVALID_MONITOR_QUERY")
			return true
		}
		hours = value
	}
	source, model := r.URL.Query().Get("sourceId"), r.URL.Query().Get("model")
	if len(source) > 160 || len(model) > 200 {
		reject(w, 400, "INVALID_MONITOR_QUERY")
		return true
	}
	all, storage, err := h.Monitor.Snapshot()
	if err != nil {
		reject(w, 503, "MODEL_MONITOR_UNAVAILABLE")
		return true
	}
	now := h.Monitor.now()
	rows := []MonitorRecord{}
	sourceModels := map[string]map[string]bool{}
	for _, row := range all {
		if sourceModels[row.SourceID] == nil {
			sourceModels[row.SourceID] = map[string]bool{}
		}
		sourceModels[row.SourceID][row.Model] = true
		if row.At > now.Add(-time.Duration(hours)*time.Hour).UnixMilli() && (source == "" || source == row.SourceID) && (model == "" || model == row.Model) {
			rows = append(rows, row)
		}
	}
	groups := []map[string]any{}
	sourceRows := map[string][]MonitorRecord{}
	for _, row := range rows {
		sourceRows[row.SourceID] = append(sourceRows[row.SourceID], row)
	}
	ids := []string{}
	for id := range sourceModels {
		ids = append(ids, id)
	}
	sort.Strings(ids)
	for _, id := range ids {
		if source == "" || source == id {
			groups = append(groups, map[string]any{"sourceId": id, "totals": summarizeMonitor(sourceRows[id])})
		}
	}
	points := []map[string]any{}
	width := int64(time.Duration(hours) * time.Hour / time.Duration(24) / time.Millisecond)
	start := now.Add(-time.Duration(hours) * time.Hour).UnixMilli()
	for index := 0; index < 24; index++ {
		from, to := start+int64(index)*width, start+int64(index+1)*width
		bucket := []MonitorRecord{}
		for _, row := range rows {
			if row.At > from && row.At <= to {
				bucket = append(bucket, row)
			}
		}
		points = append(points, map[string]any{"at": to, "totals": summarizeMonitor(bucket)})
	}
	events := []MonitorRecord{}
	for index := len(rows) - 1; index >= 0 && len(events) < 100; index-- {
		if !rows[index].Success || rows[index].Quality == "fail" {
			events = append(events, rows[index])
		}
	}
	writeJSON(w, 200, map[string]any{"data": map[string]any{"now": now.UnixMilli(), "hours": hours, "totals": summarizeMonitor(rows), "sources": groups, "models": sourceModels, "points": points, "events": events, "storage": storage}})
	return true
}
