package modelgateway

import (
	"database/sql"
	"time"
)

const callRetention = 72 * time.Hour
const retentionBatchSize = 1000

// Both sides expose the same additive measures; unknown costs remain separate counts.
const usageTotalsSQL = `(
 SELECT day,role,model,currency,agent_kind,` + usageSourceSQL + ` AS source,
  1 AS requests,COALESCE(input_tokens,0) AS input_tokens,COALESCE(output_tokens,0) AS output_tokens,
  COALESCE(cache_read_tokens,0) AS cache_read_tokens,COALESCE(cost_nano,0) AS cost_nano,
  state='pending' AS pending,state='unknown' AS unknown,
  state!='pending' AND input_tokens IS NULL AS usage_unknown,state='failed' AS failed
 FROM gateway_calls
 UNION ALL
 SELECT day,role,model,currency,agent_kind,source,requests,input_tokens,output_tokens,
  cache_read_tokens,cost_nano,0,unknown,usage_unknown,failed FROM gateway_daily_usage
)`

// Compact transfers expired receipts atomically; a late settlement starts its own retention window.
func (l *Ledger) Compact() error {
	cutoff := l.now().Add(-callRetention).UnixMilli()
	for {
		var removed int64
		err := l.db.Tx(func(tx *sql.Tx) error {
			const expired = `SELECT rowid FROM gateway_calls WHERE state!='pending' AND COALESCE(finished_ms,started_ms)<=? ORDER BY COALESCE(finished_ms,started_ms),rowid LIMIT ?`
			_, err := tx.Exec(`INSERT INTO gateway_daily_usage(day,timezone,role,model,currency,agent_kind,source,requests,input_tokens,output_tokens,cache_read_tokens,cost_nano,unknown,usage_unknown,failed)
 SELECT day,timezone,role,model,currency,agent_kind,`+usageSourceSQL+` AS source,
  count(*),COALESCE(sum(input_tokens),0),COALESCE(sum(output_tokens),0),COALESCE(sum(cache_read_tokens),0),COALESCE(sum(cost_nano),0),sum(state='unknown'),sum(input_tokens IS NULL),sum(state='failed')
 FROM gateway_calls WHERE rowid IN (`+expired+`)
 GROUP BY day,timezone,role,model,currency,agent_kind,source
 ON CONFLICT(day,timezone,role,model,currency,agent_kind,source) DO UPDATE SET
  requests=gateway_daily_usage.requests+excluded.requests,
  input_tokens=gateway_daily_usage.input_tokens+excluded.input_tokens,
  output_tokens=gateway_daily_usage.output_tokens+excluded.output_tokens,
  cache_read_tokens=gateway_daily_usage.cache_read_tokens+excluded.cache_read_tokens,
  cost_nano=gateway_daily_usage.cost_nano+excluded.cost_nano,
  unknown=gateway_daily_usage.unknown+excluded.unknown,
  usage_unknown=gateway_daily_usage.usage_unknown+excluded.usage_unknown,
  failed=gateway_daily_usage.failed+excluded.failed`, cutoff, retentionBatchSize)
			if err != nil {
				return err
			}
			result, err := tx.Exec(`DELETE FROM gateway_calls WHERE rowid IN (`+expired+`)`, cutoff, retentionBatchSize)
			if err != nil {
				return err
			}
			removed, err = result.RowsAffected()
			return err
		})
		if err != nil || removed < retentionBatchSize {
			return err
		}
	}
}
