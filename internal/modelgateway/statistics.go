package modelgateway

import (
	"database/sql"
	"fmt"
	"time"
)

// Historical evaluations already carry an RSI session ID, even when their role is main/worker.
const usageSourceSQL = `CASE WHEN substr(role,1,4)='rsi_' OR substr(session_id,1,4)='rsi-' THEN 'rsi' ELSE 'other' END`

type UsageGroup struct {
	Source       string `json:"source"`
	Day          string `json:"day"`
	Role         string `json:"role"`
	Model        string `json:"model"`
	Currency     string `json:"currency"`
	Requests     int64  `json:"requests"`
	Input        int64  `json:"inputTokens"`
	Output       int64  `json:"outputTokens"`
	Cached       int64  `json:"cacheReadTokens"`
	Pending      int64  `json:"pending"`
	Unknown      int64  `json:"unknown"`
	UsageUnknown int64  `json:"usageUnknown"`
	Failed       int64  `json:"failed"`
	Cost         string `json:"cost"`
}

type CallRecord struct {
	Source         string  `json:"source"`
	ID             string  `json:"id"`
	Day            string  `json:"day"`
	Role           string  `json:"role"`
	Model          string  `json:"model"`
	Currency       string  `json:"currency"`
	State          string  `json:"state"`
	Started        int64   `json:"startedMs"`
	Input          *int64  `json:"inputTokens"`
	Output         *int64  `json:"outputTokens"`
	Cached         *int64  `json:"cacheReadTokens"`
	Cost           *string `json:"cost"`
	Status         int     `json:"httpStatus"`
	Error          string  `json:"errorCode"`
	Reconciliation string  `json:"reconciliation"`
	Session        string  `json:"sessionId"`
	Request        string  `json:"requestId"`
}

type Statistics struct {
	Source   string        `json:"source"`
	Day      string        `json:"day"`
	Timezone string        `json:"timezone"`
	From     string        `json:"from"`
	To       string        `json:"to"`
	Days     int           `json:"days"`
	Hourly   []HourlyUsage `json:"hourly"`
	Today    []UsageGroup  `json:"today"`
	Groups   []UsageGroup  `json:"groups"`
	Recent   []CallRecord  `json:"recent"`
}

type HourlyUsage struct {
	UsageGroup
	Hour int `json:"hour"`
}

func (l *Ledger) Statistics(days int) (Statistics, error) {
	return l.StatisticsFor(days, "")
}

func (l *Ledger) StatisticsFor(days int, selected string) (Statistics, error) {
	return l.StatisticsForSource(days, selected, "")
}

func (l *Ledger) StatisticsForSource(days int, selected, source string) (Statistics, error) {
	result := Statistics{Today: []UsageGroup{}, Groups: []UsageGroup{}, Recent: []CallRecord{}, Hourly: []HourlyUsage{}, Days: days, Source: source}
	if source != "" && source != "rsi" && source != "other" {
		return result, fmt.Errorf("INVALID_MODEL_USAGE_SOURCE")
	}
	if days < 0 || days > 90 {
		return result, fmt.Errorf("INVALID_MODEL_USAGE_DAY")
	}
	err := l.db.Tx(func(tx *sql.Tx) error {
		c, err := configuration(tx)
		if err != nil {
			return err
		}
		zone, err := time.LoadLocation(c.Timezone)
		if err != nil {
			return err
		}
		today := l.now().In(zone)
		result.Day, result.Timezone, result.From = today.Format("2006-01-02"), c.Timezone, today.AddDate(0, 0, 1-days).Format("2006-01-02")
		result.To = result.Day
		if selected != "" {
			parsed, parseErr := time.Parse("2006-01-02", selected)
			if parseErr != nil || parsed.Format("2006-01-02") != selected || selected > result.Day {
				return fmt.Errorf("INVALID_MODEL_USAGE_DAY")
			}
			result.From, result.To, result.Days = selected, selected, 1
		} else if days == 0 {
			if err := tx.QueryRow(`SELECT COALESCE(MIN(day),?) FROM gateway_calls`, result.Day).Scan(&result.From); err != nil {
				return err
			}
		}
		rows, err := tx.Query(`SELECT day,role,model,currency,`+usageSourceSQL+` AS source,count(*),COALESCE(sum(input_tokens),0),COALESCE(sum(output_tokens),0),COALESCE(sum(cache_read_tokens),0),sum(state='pending'),sum(state='unknown'),sum(state!='pending' AND input_tokens IS NULL),sum(state='failed'),COALESCE(sum(cost_nano),0) FROM gateway_calls WHERE (day>=? AND day<=?) OR day=? GROUP BY day,role,model,currency,source ORDER BY day DESC,role,model,currency,source`, result.From, result.To, result.Day)
		if err != nil {
			return err
		}
		for rows.Next() {
			var group UsageGroup
			var nano int64
			if err = rows.Scan(&group.Day, &group.Role, &group.Model, &group.Currency, &group.Source, &group.Requests, &group.Input, &group.Output, &group.Cached, &group.Pending, &group.Unknown, &group.UsageUnknown, &group.Failed, &nano); err != nil {
				rows.Close()
				return err
			}
			group.Cost = money(nano)
			if group.Day >= result.From && group.Day <= result.To && (source == "" || group.Source == source) {
				result.Groups = append(result.Groups, group)
			}
			if group.Day == result.Day {
				result.Today = append(result.Today, group)
			}
		}
		err = rows.Err()
		rows.Close()
		if err != nil {
			return err
		}
		if result.Days == 1 {
			rows, err = tx.Query(`SELECT started_ms,role,model,currency,`+usageSourceSQL+`,state,input_tokens,output_tokens,cache_read_tokens,cost_nano FROM gateway_calls WHERE day=? AND (?='' OR `+usageSourceSQL+`=?)`, result.From, source, source)
			if err != nil {
				return err
			}
			type key struct {
				hour                          int
				role, model, currency, source string
			}
			groups := map[key]*HourlyUsage{}
			costs := map[key]int64{}
			for rows.Next() {
				var started int64
				var role, model, currency, rowSource, state string
				var input, output, cached, nano sql.NullInt64
				if err = rows.Scan(&started, &role, &model, &currency, &rowSource, &state, &input, &output, &cached, &nano); err != nil {
					rows.Close()
					return err
				}
				k := key{time.UnixMilli(started).In(zone).Hour(), role, model, currency, rowSource}
				if groups[k] == nil {
					groups[k] = &HourlyUsage{UsageGroup: UsageGroup{Day: result.From, Role: role, Model: model, Currency: currency, Source: rowSource}, Hour: k.hour}
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
			err = rows.Err()
			rows.Close()
			if err != nil {
				return err
			}
			for k, g := range groups {
				g.Cost = money(costs[k])
				result.Hourly = append(result.Hourly, *g)
			}
		}
		rows, err = tx.Query(`SELECT id,day,role,model,currency,state,started_ms,input_tokens,output_tokens,cache_read_tokens,cost_nano,http_status,error_code,reconciliation,session_id,request_id,`+usageSourceSQL+` FROM gateway_calls WHERE day>=? AND day<=? AND (?='' OR `+usageSourceSQL+`=?) ORDER BY started_ms DESC,id DESC LIMIT 20`, result.From, result.To, source, source)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			var record CallRecord
			var nano *int64
			if err = rows.Scan(&record.ID, &record.Day, &record.Role, &record.Model, &record.Currency, &record.State, &record.Started, &record.Input, &record.Output, &record.Cached, &nano, &record.Status, &record.Error, &record.Reconciliation, &record.Session, &record.Request, &record.Source); err != nil {
				return err
			}
			if nano != nil {
				text := money(*nano)
				record.Cost = &text
			}
			result.Recent = append(result.Recent, record)
		}
		return rows.Err()
	})
	return result, err
}
