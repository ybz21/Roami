package modelgateway

import (
	"reflect"
	"sync"
	"testing"
	"time"
)

func TestDailyRetentionPreservesAccountingAndLateReceipts(t *testing.T) {
	l := newLedger(t)
	c := testConfiguration(nil)
	c.Timezone = "Asia/Shanghai"
	if err := l.Configure(c); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 10, 25, 1, 30, 0, 0, time.UTC)
	l.now = func() time.Time { return now }
	settle := func(model, session, kind string, usage *Usage, code string) Call {
		t.Helper()
		call, err := l.Admit("main", model, session, "client-receipt", CallAttribution{AgentKind: kind})
		if err != nil {
			t.Fatal(err)
		}
		if err = l.Settle(call, usage, 200, code, false); err != nil {
			t.Fatal(err)
		}
		return call
	}
	settle("fixture", "rsi-historic", "codex", &Usage{100, 9, 10}, "")
	settle("fixture", "", "claude", nil, "MODEL_TRANSPORT_FAILED")
	settle("unpriced", "", "opencode", &Usage{123, 9, 0}, "")
	settle("fixture", "", "claude", &Usage{}, "MODEL_HTTP_401")
	pending, err := l.Admit("worker", "fixture", "", "late-receipt")
	if err != nil {
		t.Fatal(err)
	}
	now = now.Add(time.Millisecond)
	fresh := settle("fixture", "rsi-fresh", "codex", &Usage{200, 19, 20}, "")
	now = now.Add(48*time.Hour - time.Millisecond)
	before, err := l.Statistics(0)
	if err != nil {
		t.Fatal(err)
	}
	filteredBefore, err := l.StatisticsForSource(0, "", "rsi", "codex")
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		if err = l.Compact(); err != nil {
			t.Fatal(err)
		}
	}
	after, err := l.Statistics(0)
	if err != nil || before.From != after.From || !reflect.DeepEqual(before.Groups, after.Groups) || !reflect.DeepEqual(before.Today, after.Today) || len(after.Recent) != 2 {
		t.Fatalf("accounting changed: before=%+v after=%+v err=%v", before, after, err)
	}
	for _, record := range after.Recent {
		if record.ID != fresh.ID && record.ID != pending.ID {
			t.Fatalf("expired record retained: %+v", record)
		}
	}
	filteredAfter, err := l.StatisticsForSource(0, "", "rsi", "codex")
	if err != nil || !reflect.DeepEqual(filteredBefore.Groups, filteredAfter.Groups) {
		t.Fatalf("filter changed after aggregation: %+v %v", filteredAfter, err)
	}
	day, err := l.StatisticsFor(1, "2026-10-25")
	if err != nil || !day.DailyAggregated || len(day.Hourly) != 0 || day.DetailRetentionHours != 48 {
		t.Fatalf("partial hourly history exposed: %+v %v", day, err)
	}
	c.Currency = "USD"
	if err := l.Configure(c); err == nil || err.Error() != "MODEL_PROXY_CURRENCY_MISMATCH" {
		t.Fatalf("aggregated unknown costs lost their configuration guard: %v", err)
	}
	if err := l.Settle(pending, &Usage{50, 5, 0}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	if err := l.Compact(); err != nil {
		t.Fatal(err)
	}
	var count int
	if err := l.db.QueryRow(`SELECT count(*) FROM gateway_calls WHERE id=?`, pending.ID).Scan(&count); err != nil || count != 1 {
		t.Fatalf("late receipt pruned before its own retention window: %d %v", count, err)
	}
	now = now.Add(48 * time.Hour)
	if err := l.Compact(); err != nil {
		t.Fatal(err)
	}
	if err := l.db.QueryRow(`SELECT count(*) FROM gateway_calls`).Scan(&count); err != nil || count != 0 {
		t.Fatalf("expired receipts accumulated: %d %v", count, err)
	}
}

func TestDailyRetentionBatchesAndConcurrentCompactorsDoNotDoubleCount(t *testing.T) {
	l := newLedger(t)
	_, err := l.db.Exec(`WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<2505)
 INSERT INTO gateway_calls(id,day,timezone,role,model,session_id,request_id,started_ms,finished_ms,state,currency,price_json,input_tokens,output_tokens,cache_read_tokens,cost_nano)
 SELECT 'old-'||x,'2026-10-20','UTC','main','fixture','','',1,2,'known','CNY','{}',10,2,0,17 FROM n`)
	if err != nil {
		t.Fatal(err)
	}
	var wait sync.WaitGroup
	for i := 0; i < 2; i++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			if err := l.Compact(); err != nil {
				t.Error(err)
			}
		}()
	}
	wait.Wait()
	stats, err := l.Statistics(0)
	if err != nil || len(stats.Groups) != 1 || stats.Groups[0].Requests != 2505 || stats.Groups[0].Input != 25050 || stats.Groups[0].Cost != "0.000042585" || len(stats.Recent) != 0 {
		t.Fatalf("batch totals: %+v %v", stats, err)
	}
	var count int
	if err := l.db.QueryRow(`SELECT count(*) FROM gateway_daily_usage`).Scan(&count); err != nil || count != 1 {
		t.Fatalf("receipts were not reduced to one daily row: %d %v", count, err)
	}
}

func TestDailyRetentionRollsBackAggregationIfDeletionFails(t *testing.T) {
	l := newLedger(t)
	_, err := l.db.Exec(`INSERT INTO gateway_calls(id,day,timezone,role,model,session_id,request_id,started_ms,finished_ms,state,currency,price_json,cost_nano)
 VALUES('old','2026-10-20','UTC','main','fixture','','',1,2,'unknown','CNY','{}',NULL);
 CREATE TRIGGER fail_retention_delete BEFORE DELETE ON gateway_calls BEGIN SELECT RAISE(ABORT,'fixture deletion failure'); END;`)
	if err != nil {
		t.Fatal(err)
	}
	if err := l.Compact(); err == nil {
		t.Fatal("expected deletion failure")
	}
	var calls, daily int
	if err := l.db.QueryRow(`SELECT (SELECT count(*) FROM gateway_calls),(SELECT count(*) FROM gateway_daily_usage)`).Scan(&calls, &daily); err != nil || calls != 1 || daily != 0 {
		t.Fatalf("partial accounting transfer: calls=%d daily=%d err=%v", calls, daily, err)
	}
	if _, err := l.db.Exec(`DROP TRIGGER fail_retention_delete`); err != nil {
		t.Fatal(err)
	}
	if err := l.Compact(); err != nil {
		t.Fatal(err)
	}
	stats, err := l.Statistics(0)
	if err != nil || len(stats.Groups) != 1 || stats.Groups[0].Unknown != 1 || stats.Groups[0].UsageUnknown != 1 {
		t.Fatalf("unknown receipt lost: %+v %v", stats, err)
	}
}

func TestDailyRetentionNeverRoundsOverflowingMoney(t *testing.T) {
	l := newLedger(t)
	_, err := l.db.Exec(`INSERT INTO gateway_daily_usage VALUES('2026-10-20','UTC','main','fixture','CNY','roami','other',1,0,0,0,9223372036854775807,0,0,0,'');
 INSERT INTO gateway_calls(id,day,timezone,role,model,session_id,request_id,started_ms,finished_ms,state,currency,price_json,cost_nano)
 VALUES('old','2026-10-20','UTC','main','fixture','','',1,2,'known','CNY','{}',1)`)
	if err != nil {
		t.Fatal(err)
	}
	if err := l.Compact(); err == nil {
		t.Fatal("overflowing money was rounded to floating point")
	}
	var calls int
	var money int64
	if err := l.db.QueryRow(`SELECT (SELECT count(*) FROM gateway_calls),cost_nano FROM gateway_daily_usage`).Scan(&calls, &money); err != nil || calls != 1 || money != 9223372036854775807 {
		t.Fatalf("overflow changed ledger: calls=%d money=%d err=%v", calls, money, err)
	}
}
