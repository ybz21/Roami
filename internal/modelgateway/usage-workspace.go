package modelgateway

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"time"
)

type UsageQuery struct {
	View, Start, End, Source, Agent, SourceID, Model, State, Search string
	Timezone                                                        string
	zone                                                            *time.Location
	daySQL                                                          string
	Days, Page                                                      int
	MissingSource                                                   bool
	Day                                                             string
	Hour                                                            *int
}

type UsageDimensions struct {
	Sources []string `json:"sources"`
	Agents  []string `json:"agents"`
	Models  []string `json:"models"`
}

type WorkspaceUsage struct {
	Statistics
	Options            UsageDimensions `json:"options"`
	Total              int             `json:"total"`
	Page               int             `json:"page"`
	PageSize           int             `json:"pageSize"`
	Archived           int64           `json:"archived"`
	HourlyDay          string          `json:"hourlyDay"`
	AccountingTimezone string          `json:"accountingTimezone"`
}

func workspaceQuery(v url.Values) (UsageQuery, error) {
	q := UsageQuery{View: v.Get("view"), Start: v.Get("start"), End: v.Get("end"), Source: v.Get("source"), Agent: v.Get("agentKind"), SourceID: v.Get("sourceId"), Model: v.Get("model"), State: v.Get("state"), Search: strings.TrimSpace(v.Get("q")), Days: 7, Page: 1, MissingSource: v.Get("unattributed") == "1"}
	q.Day = v.Get("day")
	q.Timezone = v.Get("timezone")
	if q.Timezone != "" {
		if len(q.Timezone) > 100 || q.Timezone == "Local" {
			return q, fmt.Errorf("INVALID_MODEL_USAGE_QUERY")
		}
		if _, err := time.LoadLocation(q.Timezone); err != nil {
			return q, fmt.Errorf("INVALID_MODEL_USAGE_QUERY")
		}
	}
	if raw := v.Get("hour"); raw != "" {
		hour, err := strconv.Atoi(raw)
		if err != nil || hour < 0 || hour > 23 || q.Day == "" || q.View != "audit" {
			return q, fmt.Errorf("INVALID_MODEL_USAGE_QUERY")
		}
		q.Hour = &hour
	}
	if raw := v.Get("days"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil {
			return q, fmt.Errorf("INVALID_MODEL_USAGE_DAY")
		}
		q.Days = n
	}
	if raw := v.Get("page"); raw != "" {
		n, err := strconv.Atoi(raw)
		if err != nil {
			return q, fmt.Errorf("INVALID_MODEL_USAGE_QUERY")
		}
		q.Page = n
	}
	if q.View != "overview" && q.View != "audit" || q.Page < 1 || q.Page > 1_000_000 || len(q.Search) > 200 || len(q.SourceID) > 200 || len(q.Model) > 200 || q.MissingSource && q.SourceID != "" {
		return q, fmt.Errorf("INVALID_MODEL_USAGE_QUERY")
	}
	if q.Days < 0 || q.Days > 90 {
		return q, fmt.Errorf("INVALID_MODEL_USAGE_DAY")
	}
	if q.Source != "" && q.Source != "rsi" && q.Source != "other" {
		return q, fmt.Errorf("INVALID_MODEL_USAGE_SOURCE")
	}
	if q.Agent != "" && q.Agent != "external" && !containsField(gatewayAgentKinds, q.Agent) {
		return q, fmt.Errorf("INVALID_AGENT_KIND")
	}
	if q.State != "" && !containsField([]string{"pending", "known", "unknown", "failed"}, q.State) {
		return q, fmt.Errorf("INVALID_MODEL_USAGE_STATE")
	}
	return q, nil
}

func (q UsageQuery) where(source string) (string, []any) {
	window, bounds := `day>=? AND day<=?`, []any{q.Start, q.End}
	if source == usageSourceSQL && q.zone != nil {
		from, _ := time.ParseInLocation("2006-01-02", q.Start, q.zone)
		to, _ := time.ParseInLocation("2006-01-02", q.End, q.zone)
		window, bounds = `started_ms>=? AND started_ms<?`, []any{from.UnixMilli(), to.AddDate(0, 0, 1).UnixMilli()}
	}
	return window + ` AND (?='' OR ` + source + `=?) AND (?='' OR agent_kind=?) AND (?='' OR source_id=?) AND (?=0 OR source_id='') AND (?='' OR model=?)`, append(bounds, q.Source, q.Source, q.Agent, q.Agent, q.SourceID, q.SourceID, q.MissingSource, q.Model, q.Model)
}

func readWorkspaceGroups(tx *sql.Tx, where string, args []any, tables ...string) ([]UsageGroup, error) {
	table := usageTotalsSQL
	if len(tables) > 0 {
		table = tables[0]
	}
	rows, err := tx.Query(`SELECT day,role,model,currency,agent_kind,source,source_id,sum(requests),sum(input_tokens),sum(output_tokens),sum(cache_read_tokens),sum(pending),sum(unknown),sum(usage_unknown),sum(failed),sum(cost_nano) FROM `+table+` WHERE `+where+` GROUP BY day,role,model,currency,agent_kind,source,source_id ORDER BY day,source_id,agent_kind,model,currency`, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []UsageGroup{}
	for rows.Next() {
		var g UsageGroup
		var nano int64
		if err = rows.Scan(&g.Day, &g.Role, &g.Model, &g.Currency, &g.AgentKind, &g.Source, &g.SourceID, &g.Requests, &g.Input, &g.Output, &g.Cached, &g.Pending, &g.Unknown, &g.UsageUnknown, &g.Failed, &nano); err != nil {
			return nil, err
		}
		g.Cost = money(nano)
		result = append(result, g)
	}
	return result, rows.Err()
}

func (l *Ledger) WorkspaceUsage(q UsageQuery) (WorkspaceUsage, error) {
	result := WorkspaceUsage{Statistics: Statistics{Today: []UsageGroup{}, Groups: []UsageGroup{}, Recent: []CallRecord{}, Hourly: []HourlyUsage{}, DetailRetentionHours: int(callRetention / time.Hour)}, Page: q.Page, PageSize: 20, Options: UsageDimensions{Sources: []string{}, Agents: []string{}, Models: []string{}}}
	err := l.db.Tx(func(tx *sql.Tx) error {
		c, err := configuration(tx)
		if err != nil {
			return err
		}
		result.AccountingTimezone = c.Timezone
		timezone := c.Timezone
		if q.Timezone != "" {
			timezone = q.Timezone
		}
		zone, err := time.LoadLocation(timezone)
		if err != nil {
			return err
		}
		now := l.now().In(zone)
		today := now.Format("2006-01-02")
		q.zone = zone
		result.Day, result.Timezone = today, timezone
		if q.Start == "" && q.End == "" {
			q.Start, q.End = now.AddDate(0, 0, 1-q.Days).Format("2006-01-02"), today
			if q.Days == 0 {
				if err = tx.QueryRow(`SELECT COALESCE(MIN(day),?) FROM `+usageTotalsSQL, today).Scan(&q.Start); err != nil {
					return err
				}
				var first sql.NullInt64
				if err = tx.QueryRow(`SELECT MIN(started_ms) FROM gateway_calls`).Scan(&first); err != nil {
					return err
				}
				if first.Valid {
					if day := time.UnixMilli(first.Int64).In(zone).Format("2006-01-02"); day < q.Start {
						q.Start = day
					}
				}
			}
		}
		for _, day := range []string{q.Start, q.End} {
			parsed, e := time.Parse("2006-01-02", day)
			if e != nil || parsed.Format("2006-01-02") != day || day > today {
				return fmt.Errorf("INVALID_MODEL_USAGE_DAY")
			}
		}
		if q.Start > q.End {
			return fmt.Errorf("INVALID_MODEL_USAGE_DAY")
		}
		result.From, result.To = q.Start, q.End
		from, _ := time.Parse("2006-01-02", q.Start)
		to, _ := time.Parse("2006-01-02", q.End)
		result.Days = int(to.Sub(from).Hours()/24) + 1
		totalsTable, err := workspaceTotalsTable(tx, &q, c.Timezone)
		if err != nil {
			return err
		}
		where, args := q.where("source")
		result.Groups, err = readWorkspaceGroups(tx, where, args, totalsTable)
		if err != nil {
			return err
		}
		if q.View == "overview" {
			// Admission and today's balance always cover every caller, independently of analysis filters.
			accountingZone, _ := time.LoadLocation(c.Timezone)
			result.Today, err = readWorkspaceGroups(tx, "day=?", []any{l.now().In(accountingZone).Format("2006-01-02")})
			if err != nil {
				return err
			}
		}
		if err = tx.QueryRow(`SELECT COALESCE(sum(requests),0) FROM gateway_daily_usage WHERE `+where, args...).Scan(&result.Archived); err != nil {
			return err
		}
		result.HourlyDay = q.Day
		if result.HourlyDay == "" {
			result.HourlyDay = q.End
		}
		if result.HourlyDay < q.Start || result.HourlyDay > q.End {
			return fmt.Errorf("INVALID_MODEL_USAGE_DAY")
		}
		selectedDay, parseErr := time.ParseInLocation("2006-01-02", result.HourlyDay, zone)
		if parseErr != nil || selectedDay.Format("2006-01-02") != result.HourlyDay {
			return fmt.Errorf("INVALID_MODEL_USAGE_DAY")
		}
		hourQuery := q
		hourQuery.Start, hourQuery.End = result.HourlyDay, result.HourlyDay
		hourWhere, hourArgs := hourQuery.where("source")
		if err = tx.QueryRow(`SELECT EXISTS(SELECT 1 FROM gateway_daily_usage WHERE `+hourWhere+`)`, hourArgs...).Scan(&result.DailyAggregated); err != nil {
			return err
		}
		if selectedDay.AddDate(0, 0, 1).Before(l.now().Add(-callRetention)) {
			result.DailyAggregated = true
		}
		if q.View == "overview" {
			result.Hourly, err = readWorkspaceHours(tx, hourQuery, zone)
			if err != nil {
				return err
			}
		}
		if q.Hour != nil {
			result.Archived = 0
		}
		rows, err := tx.Query(`SELECT DISTINCT source_id,agent_kind,model FROM `+totalsTable+` WHERE day>=? AND day<=?`, q.Start, q.End)
		if err != nil {
			return err
		}
		sourceSet, agentSet, modelSet := map[string]bool{}, map[string]bool{}, map[string]bool{}
		for rows.Next() {
			var source, agent, model string
			if err = rows.Scan(&source, &agent, &model); err != nil {
				rows.Close()
				return err
			}
			sourceSet[source], agentSet[agent], modelSet[model] = true, true, true
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return err
		}
		for s := range sourceSet {
			result.Options.Sources = append(result.Options.Sources, s)
		}
		for s := range agentSet {
			result.Options.Agents = append(result.Options.Agents, s)
		}
		for s := range modelSet {
			result.Options.Models = append(result.Options.Models, s)
		}
		sort.Strings(result.Options.Sources)
		sort.Strings(result.Options.Agents)
		sort.Strings(result.Options.Models)
		if q.View != "audit" {
			return nil
		}
		where, args = q.where(usageSourceSQL)
		if q.Hour != nil {
			var ranges []string
			var start *time.Time
			end := selectedDay.AddDate(0, 0, 1)
			// DST changes can repeat only part of an hour, as in Australia/Lord_Howe.
			for instant := selectedDay; !instant.After(end); instant = instant.Add(time.Minute) {
				matches := instant.Before(end) && instant.In(zone).Hour() == *q.Hour
				if matches && start == nil {
					value := instant
					start = &value
				}
				if !matches && start != nil {
					ranges = append(ranges, `(started_ms>=? AND started_ms<?)`)
					args = append(args, start.UnixMilli(), instant.UnixMilli())
					start = nil
				}
			}
			if len(ranges) == 0 {
				where += ` AND 0`
			} else {
				where += ` AND (` + strings.Join(ranges, " OR ") + `)`
			}
		}
		where += ` AND (?='' OR state=?) AND (?='' OR instr(lower(model),lower(?))>0 OR instr(lower(id),lower(?))>0 OR instr(lower(request_id),lower(?))>0 OR instr(lower(upstream_request_id),lower(?))>0)`
		args = append(args, q.State, q.State, q.Search, q.Search, q.Search, q.Search, q.Search)
		if q.Hour != nil || q.State != "" || q.Search != "" {
			callTotals := `(SELECT ` + q.daySQL + ` AS day,role,model,currency,agent_kind,` + usageSourceSQL + ` AS source,source_id,1 AS requests,COALESCE(input_tokens,0) AS input_tokens,COALESCE(output_tokens,0) AS output_tokens,COALESCE(cache_read_tokens,0) AS cache_read_tokens,COALESCE(cost_nano,0) AS cost_nano,state='pending' AS pending,state='unknown' AS unknown,state!='pending' AND input_tokens IS NULL AS usage_unknown,state='failed' AS failed FROM gateway_calls WHERE ` + where + `)`
			result.Groups, err = readWorkspaceGroups(tx, "1", args, callTotals)
			if err != nil {
				return err
			}
		}
		if err = tx.QueryRow(`SELECT count(*) FROM gateway_calls WHERE `+where, args...).Scan(&result.Total); err != nil {
			return err
		}
		lastPage := (result.Total + result.PageSize - 1) / result.PageSize
		if lastPage < 1 {
			lastPage = 1
		}
		if result.Page > lastPage {
			result.Page = lastPage
		}
		rows, err = tx.Query(`SELECT id,`+q.daySQL+`,role,model,currency,state,started_ms,input_tokens,output_tokens,cache_read_tokens,cost_nano,http_status,error_code,reconciliation,session_id,request_id,agent_kind,key_id,source_id,route_id,price_status,upstream_http_status,upstream_request_id,`+usageSourceSQL+`,price_json,finished_ms FROM gateway_calls WHERE `+where+` ORDER BY started_ms DESC,id DESC LIMIT ? OFFSET ?`, append(args, result.PageSize, (result.Page-1)*result.PageSize)...)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var r CallRecord
			var nano *int64
			var price string
			if err = rows.Scan(&r.ID, &r.Day, &r.Role, &r.Model, &r.Currency, &r.State, &r.Started, &r.Input, &r.Output, &r.Cached, &nano, &r.Status, &r.Error, &r.Reconciliation, &r.Session, &r.Request, &r.AgentKind, &r.KeyID, &r.SourceID, &r.RouteID, &r.PriceStatus, &r.UpstreamStatus, &r.UpstreamRequest, &r.Source, &price, &r.Finished); err != nil {
				return err
			}
			if nano != nil {
				text := money(*nano)
				r.Cost = &text
			}
			if r.PriceStatus != "unpriced" {
				var p ModelPricing
				if err = json.Unmarshal([]byte(price), &p); err != nil {
					return err
				}
				r.Price = &p
			}
			result.Recent = append(result.Recent, r)
		}
		return rows.Err()
	})
	return result, err
}

func readWorkspaceHours(tx *sql.Tx, q UsageQuery, zone *time.Location) ([]HourlyUsage, error) {
	where, args := q.where(usageSourceSQL)
	rows, err := tx.Query(`SELECT started_ms,role,model,currency,agent_kind,`+usageSourceSQL+`,source_id,state,input_tokens,output_tokens,cache_read_tokens,cost_nano FROM gateway_calls WHERE `+where, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	type key struct {
		hour                                     int
		role, model, currency, agent, source, id string
	}
	groups := map[key]*HourlyUsage{}
	costs := map[key]int64{}
	for rows.Next() {
		var started int64
		var k key
		var state string
		var input, output, cached, nano sql.NullInt64
		if err = rows.Scan(&started, &k.role, &k.model, &k.currency, &k.agent, &k.source, &k.id, &state, &input, &output, &cached, &nano); err != nil {
			return nil, err
		}
		k.hour = time.UnixMilli(started).In(zone).Hour()
		if groups[k] == nil {
			groups[k] = &HourlyUsage{UsageGroup: UsageGroup{Day: q.Start, Role: k.role, Model: k.model, Currency: k.currency, AgentKind: k.agent, Source: k.source, SourceID: k.id}, Hour: k.hour}
		}
		g := groups[k]
		g.Requests++
		g.Input += input.Int64
		g.Output += output.Int64
		g.Cached += cached.Int64
		costs[k] += nano.Int64
		if state == "pending" {
			g.Pending++
		}
		if state == "unknown" {
			g.Unknown++
		}
		if state == "failed" {
			g.Failed++
		}
		if state != "pending" && !input.Valid {
			g.UsageUnknown++
		}
	}
	result := []HourlyUsage{}
	for k, g := range groups {
		g.Cost = money(costs[k])
		result = append(result, *g)
	}
	sort.Slice(result, func(i, j int) bool {
		a, b := result[i], result[j]
		if a.Hour != b.Hour {
			return a.Hour < b.Hour
		}
		return strings.Join([]string{a.SourceID, a.AgentKind, a.Model, a.Currency, a.Role, a.Source}, "\x00") < strings.Join([]string{b.SourceID, b.AgentKind, b.Model, b.Currency, b.Role, b.Source}, "\x00")
	})
	return result, rows.Err()
}
