package monitor

import (
	"math"
	"sort"
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
func summarizeMonitor(rows []Record) monitorTotals {
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
func AttemptsReport(all []Record, storage map[string]any, now time.Time, hours int, source, model string) map[string]any {
	rows := []Record{}
	sourceModels := map[string]map[string]bool{}
	for _, row := range all {
		if row.Outcome != "" {
			continue
		}
		if sourceModels[row.SourceID] == nil {
			sourceModels[row.SourceID] = map[string]bool{}
		}
		sourceModels[row.SourceID][row.Model] = true
		if row.At > now.Add(-time.Duration(hours)*time.Hour).UnixMilli() && (source == "" || source == row.SourceID) && (model == "" || model == row.Model) {
			rows = append(rows, row)
		}
	}
	groups := []map[string]any{}
	sourceRows := map[string][]Record{}
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
		bucket := []Record{}
		for _, row := range rows {
			if row.At > from && row.At <= to {
				bucket = append(bucket, row)
			}
		}
		points = append(points, map[string]any{"at": to, "totals": summarizeMonitor(bucket)})
	}
	events := []Record{}
	for index := len(rows) - 1; index >= 0 && len(events) < 100; index-- {
		if !rows[index].Success || rows[index].Quality == "fail" {
			events = append(events, rows[index])
		}
	}
	return map[string]any{"now": now.UnixMilli(), "hours": hours, "totals": summarizeMonitor(rows), "sources": groups, "models": sourceModels, "points": points, "events": events, "storage": storage}
}
