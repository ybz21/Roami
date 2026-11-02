package modelgateway

import (
	"testing"
	"time"
)

func TestUsageDateSelectionHourlyAndLifetimeKeepTodaySeparate(t *testing.T) {
	l := newLedger(t)
	c := testConfiguration(nil)
	c.Timezone = "Asia/Shanghai"
	if err := l.Configure(c); err != nil {
		t.Fatal(err)
	}
	l.now = func() time.Time { return time.Date(2026, 10, 28, 1, 0, 0, 0, time.UTC) }
	call, err := l.Admit("main", "fixture", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(call, &Usage{100, 20, 10}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	l.now = func() time.Time { return time.Date(2026, 10, 29, 2, 0, 0, 0, time.UTC) }
	call, err = l.Admit("worker", "fixture", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(call, &Usage{200, 30, 20}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	selected, err := l.StatisticsFor(1, "2026-10-28")
	if err != nil {
		t.Fatal(err)
	}
	if len(selected.Groups) != 1 || selected.Groups[0].Input != 100 || len(selected.Today) != 1 || selected.Today[0].Input != 200 || len(selected.Hourly) != 1 || selected.Hourly[0].Hour != 9 {
		t.Fatalf("periods mixed: %+v", selected)
	}
	all, err := l.Statistics(0)
	if err != nil || all.From != "2026-10-28" || len(all.Groups) != 2 {
		t.Fatalf("lifetime: %+v %v", all, err)
	}
	if _, err = l.StatisticsFor(1, "2026-10-30"); err == nil {
		t.Fatal("future date accepted")
	}
	if _, err = l.StatisticsFor(1, "2026-10-32"); err == nil {
		t.Fatal("invalid date accepted")
	}
}
