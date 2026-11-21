package modelgateway

import (
	"math"
	"slices"
	"sort"
)

type requestSummaryFilter struct {
	from, to                          int64
	routeIDs                          []string
	caller, outcome, reason, switched string
}

type requestSummaryRange struct {
	From int64 `json:"from"`
	To   int64 `json:"to"`
}

type requestPercentiles struct {
	Samples int     `json:"samples"`
	P50     float64 `json:"p50"`
	P95     float64 `json:"p95"`
	P99     float64 `json:"p99"`
}

func summarizeRequestLatency(values []float64) *requestPercentiles {
	if len(values) == 0 {
		return nil
	}
	slices.Sort(values)
	at := func(q float64) float64 { return values[int(math.Ceil(q*float64(len(values))))-1] }
	return &requestPercentiles{Samples: len(values), P50: at(.50), P95: at(.95), P99: at(.99)}
}

type requestTokenSummary struct {
	monitorTokenUsage
	Samples int `json:"samples"`
}

type requestSummaryGroup struct {
	ID     string        `json:"id"`
	Totals requestTotals `json:"totals"`
}

func requestSummaryGroups(groups map[string]*requestTotals) []requestSummaryGroup {
	result := make([]requestSummaryGroup, 0, len(groups))
	for id, totals := range groups {
		result = append(result, requestSummaryGroup{ID: id, Totals: *totals})
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

type requestSummary struct {
	Now            int64                 `json:"now"`
	Range          requestSummaryRange   `json:"range"`
	Totals         requestTotals         `json:"totals"`
	Points         []requestBucket       `json:"points"`
	Routes         map[string]string     `json:"routes"`
	Callers        map[string]bool       `json:"callers"`
	Outcomes       map[string]int        `json:"outcomes"`
	FailureReasons map[string]int        `json:"failureReasons"`
	FirstToken     *requestPercentiles   `json:"firstToken"`
	Duration       *requestPercentiles   `json:"duration"`
	Tokens         requestTokenSummary   `json:"tokens"`
	ByModel        []requestSummaryGroup `json:"byModel"`
	BySource       []requestSummaryGroup `json:"bySource"`
}

func summarizeRequests(rows []MonitorRecord, points []requestBucket, filter requestSummaryFilter) requestSummary {
	start, end := points[0].From, points[len(points)-1].To
	span := points[0].To - start
	result := requestSummary{
		Now: end, Range: requestSummaryRange{From: filter.from, To: filter.to}, Points: points,
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
	models, sources := map[string]*requestTotals{}, map[string]*requestTotals{}
	addGroup := func(groups map[string]*requestTotals, id string, row MonitorRecord) {
		if groups[id] == nil {
			groups[id] = &requestTotals{}
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
		if row.At <= start || row.At > end || len(filter.routeIDs) != 0 && !slices.Contains(filter.routeIDs, row.RouteID) ||
			filter.caller != "" && row.Caller != filter.caller {
			continue
		}
		outcome, reason := requestOutcomeKey(row), requestFailureReason(row)
		inSample := row.At > filter.from && row.At <= filter.to
		// Keep sibling facet counts available while a result or reason filter is selected.
		if inSample {
			result.Outcomes[outcome]++
			if reason != "" {
				result.FailureReasons[reason]++
			}
		}
		if filter.outcome != "" && outcome != filter.outcome || filter.reason != "" && reason != filter.reason || !matchesRequestSwitch(row, filter.switched, reason) {
			continue
		}
		points[(row.At-start-1)/span].Totals.add(row)
		if !inSample {
			continue
		}
		result.Totals.add(row)
		addGroup(models, row.RouteID, row)
		addGroup(sources, row.SourceID, row)
		if outcome != "success" && outcome != "recovered" {
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
