package monitor

import (
	"math"
	"slices"
	"sort"
)

type RequestFilter struct {
	From, To                          int64
	RouteIDs                          []string
	Caller, Outcome, Reason, Switched string
}

type RequestSummaryRange struct {
	From int64 `json:"from"`
	To   int64 `json:"to"`
}

type RequestPercentiles struct {
	Samples int     `json:"samples"`
	P50     float64 `json:"p50"`
	P95     float64 `json:"p95"`
	P99     float64 `json:"p99"`
}

func summarizeRequestLatency(values []float64) *RequestPercentiles {
	if len(values) == 0 {
		return nil
	}
	slices.Sort(values)
	at := func(q float64) float64 { return values[int(math.Ceil(q*float64(len(values))))-1] }
	return &RequestPercentiles{Samples: len(values), P50: at(.50), P95: at(.95), P99: at(.99)}
}

type RequestTokenSummary struct {
	TokenUsage
	Samples int `json:"samples"`
}

type RequestSummaryGroup struct {
	ID     string        `json:"id"`
	Totals RequestTotals `json:"totals"`
}

func requestSummaryGroups(groups map[string]*RequestTotals) []RequestSummaryGroup {
	result := make([]RequestSummaryGroup, 0, len(groups))
	for id, totals := range groups {
		result = append(result, RequestSummaryGroup{ID: id, Totals: *totals})
	}
	sort.Slice(result, func(i, j int) bool {
		a, b := result[i], result[j]
		if a.Totals.Requests != b.Totals.Requests {
			return a.Totals.Requests > b.Totals.Requests
		}
		return a.ID < b.ID
	})
	return result
}

type RequestSummary struct {
	Now            int64                 `json:"now"`
	Range          RequestSummaryRange   `json:"range"`
	Totals         RequestTotals         `json:"totals"`
	Points         []RequestBucket       `json:"points"`
	Routes         map[string]string     `json:"routes"`
	Callers        map[string]bool       `json:"callers"`
	Outcomes       map[string]int        `json:"outcomes"`
	FailureReasons map[string]int        `json:"failureReasons"`
	FirstToken     *RequestPercentiles   `json:"firstToken"`
	Duration       *RequestPercentiles   `json:"duration"`
	Tokens         RequestTokenSummary   `json:"tokens"`
	ByModel        []RequestSummaryGroup `json:"byModel"`
	BySource       []RequestSummaryGroup `json:"bySource"`
}

func SummarizeRequests(rows []Record, points []RequestBucket, filter RequestFilter) RequestSummary {
	start, end := points[0].From, points[len(points)-1].To
	span := points[0].To - start
	result := RequestSummary{
		Now: end, Range: RequestSummaryRange{From: filter.From, To: filter.To}, Points: points,
		Routes: map[string]string{}, Callers: map[string]bool{}, Outcomes: map[string]int{}, FailureReasons: map[string]int{},
	}
	type attemptKey struct {
		request string
		attempt int
	}
	firstTokenByAttempt := map[attemptKey]float64{}
	for _, row := range rows {
		if row.Outcome == "" && row.Success && row.RequestID != "" && row.FirstToken != nil {
			firstTokenByAttempt[attemptKey{row.RequestID, row.Attempt}] = *row.FirstToken
		}
	}

	var first, duration []float64
	models, sources := map[string]*RequestTotals{}, map[string]*RequestTotals{}
	addGroup := func(groups map[string]*RequestTotals, id string, row Record) {
		if groups[id] == nil {
			groups[id] = &RequestTotals{}
		}
		groups[id].add(row)
	}
	for index := len(rows) - 1; index >= 0; index-- {
		row := rows[index]
		if row.Outcome == "" {
			continue
		}
		if _, known := result.Routes[row.RouteID]; !known {
			result.Routes[row.RouteID] = row.Model
		}
		result.Callers[row.Caller] = true
		if row.At <= start || row.At > end || len(filter.RouteIDs) != 0 && !slices.Contains(filter.RouteIDs, row.RouteID) ||
			filter.Caller != "" && row.Caller != filter.Caller {
			continue
		}
		Outcome, Reason := requestOutcomeKey(row), FailureReason(row)
		inSample := row.At > filter.From && row.At <= filter.To
		// Keep sibling facet counts available while a result or Reason filter is selected.
		if inSample {
			result.Outcomes[Outcome]++
			if Reason != "" {
				result.FailureReasons[Reason]++
			}
		}
		if filter.Outcome != "" && Outcome != filter.Outcome || filter.Reason != "" && Reason != filter.Reason || !matchesRequestSwitch(row, filter.Switched, Reason) {
			continue
		}
		points[(row.At-start-1)/span].Totals.add(row)
		if !inSample {
			continue
		}
		result.Totals.add(row)
		addGroup(models, row.RouteID, row)
		addGroup(sources, row.SourceID, row)
		if Outcome != "success" && Outcome != "recovered" {
			continue
		}
		duration = append(duration, float64(row.Duration))
		if row.FirstToken != nil {
			first = append(first, *row.FirstToken)
		} else if latency, found := firstTokenByAttempt[attemptKey{row.RequestID, row.Attempts}]; found {
			first = append(first, latency)
		}
		if usage := row.TokenUsage; usage != nil {
			result.Tokens.Samples++
			result.Tokens.Input += usage.Input
			result.Tokens.Output += usage.Output
		}
	}
	result.FirstToken, result.Duration = summarizeRequestLatency(first), summarizeRequestLatency(duration)
	result.ByModel, result.BySource = requestSummaryGroups(models), requestSummaryGroups(sources)
	return result
}
