package modelgateway

import (
	"database/sql"
	"fmt"
	"sort"
	"strings"
	"time"
)

// Archived totals have no timestamps; retain their original accounting dates.
func workspaceTotalsTable(tx *sql.Tx, q *UsageQuery, accountingTimezone string) (string, error) {
	q.daySQL = "day"
	if q.Timezone == "" || q.Timezone == accountingTimezone {
		return usageTotalsSQL, nil
	}
	rangeQuery := *q
	rangeQuery.Source, rangeQuery.Agent, rangeQuery.SourceID, rangeQuery.Model, rangeQuery.MissingSource = "", "", "", "", false
	where, args := rangeQuery.where(usageSourceSQL)
	rows, err := tx.Query(`SELECT DISTINCT started_ms/86400000 FROM gateway_calls WHERE `+where, args...)
	if err != nil {
		return "", err
	}
	dates := map[string]bool{}
	for rows.Next() {
		var day int64
		if err = rows.Scan(&day); err != nil {
			rows.Close()
			return "", err
		}
		first := time.UnixMilli(day * 86400000)
		for instant := first; instant.Before(first.Add(24 * time.Hour)); instant = instant.Add(time.Hour) {
			key := instant.In(q.zone).Format("2006-01-02")
			if key >= q.Start && key <= q.End {
				dates[key] = true
			}
		}
		key := first.Add(24*time.Hour - time.Millisecond).In(q.zone).Format("2006-01-02")
		if key >= q.Start && key <= q.End {
			dates[key] = true
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return "", err
	}
	windows := []string{}
	dayCases := []string{}
	for day := range dates {
		start, _ := time.ParseInLocation("2006-01-02", day, q.zone)
		dayCases = append(dayCases, fmt.Sprintf("WHEN started_ms>=%d AND started_ms<%d THEN '%s'", start.UnixMilli(), start.AddDate(0, 0, 1).UnixMilli(), day))
		windows = append(windows, fmt.Sprintf("('%s',%d,%d)", day, start.UnixMilli(), start.AddDate(0, 0, 1).UnixMilli()))
	}
	sort.Strings(windows)
	sort.Strings(dayCases)
	if len(dayCases) > 0 {
		q.daySQL = "CASE " + strings.Join(dayCases, " ") + " ELSE day END"
	}
	if len(windows) == 0 {
		return `(SELECT *,0 AS pending FROM gateway_daily_usage)`, nil
	}
	return `(WITH local_days(local_day,start_ms,end_ms) AS (VALUES ` + strings.Join(windows, ",") + `)
 SELECT local_day AS day,role,model,currency,agent_kind,` + usageSourceSQL + ` AS source,source_id,
 1 AS requests,COALESCE(input_tokens,0) AS input_tokens,COALESCE(output_tokens,0) AS output_tokens,
 COALESCE(cache_read_tokens,0) AS cache_read_tokens,COALESCE(cost_nano,0) AS cost_nano,
 state='pending' AS pending,state='unknown' AS unknown,state!='pending' AND input_tokens IS NULL AS usage_unknown,state='failed' AS failed
 FROM gateway_calls JOIN local_days ON started_ms>=start_ms AND started_ms<end_ms
 UNION ALL SELECT day,role,model,currency,agent_kind,source,source_id,requests,input_tokens,output_tokens,cache_read_tokens,cost_nano,0,unknown,usage_unknown,failed FROM gateway_daily_usage)`, nil
}
