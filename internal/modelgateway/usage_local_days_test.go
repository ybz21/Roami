package modelgateway

import (
	"net/url"
	"reflect"
	"testing"
	"time"
)

func TestWorkspaceViewingTimezoneCrossesAccountingMidnight(t *testing.T) {
	l := newLedger(t)
	config := testConfiguration(nil)
	if err := l.Configure(config); err != nil {
		t.Fatal(err)
	}
	for _, at := range []string{"2026-11-13T15:30:00Z", "2026-11-13T16:15:00Z", "2026-11-13T23:30:00Z", "2026-11-14T00:15:00Z"} {
		instant, _ := time.Parse(time.RFC3339, at)
		l.now = func() time.Time { return instant }
		call, err := l.Admit("main", "fixture", "", at, CallAttribution{SourceID: "a", AgentKind: "codex"})
		if err != nil {
			t.Fatal(err)
		}
		if err = l.Settle(call, &Usage{Input: 100, Output: 20}, 200, "", false); err != nil {
			t.Fatal(err)
		}
	}
	query := UsageQuery{View: "overview", Days: 1, Page: 1, Timezone: "Asia/Shanghai"}
	result, err := l.WorkspaceUsage(query)
	if err != nil || result.Timezone != "Asia/Shanghai" || result.Day != "2026-11-14" || len(result.Groups) != 1 || result.Groups[0].Requests != 3 || result.Groups[0].Day != "2026-11-14" {
		t.Fatalf("local day: %+v %v", result, err)
	}
	if result.AccountingTimezone != "UTC" || len(result.Today) != 1 || result.Today[0].Requests != 1 {
		t.Fatalf("viewing zone changed quota period: %+v", result)
	}
	hours := []int{}
	for _, row := range result.Hourly {
		hours = append(hours, row.Hour)
	}
	if !reflect.DeepEqual(hours, []int{0, 7, 8}) {
		t.Fatalf("local hours: %v", hours)
	}
	query.View, query.Day = "audit", result.Day
	hour := 0
	query.Hour = &hour
	audit, err := l.WorkspaceUsage(query)
	if err != nil || audit.Total != 1 || audit.Recent[0].Request != "2026-11-13T16:15:00Z" || audit.Groups[0].Day != "2026-11-14" {
		t.Fatalf("local drill-down: %+v %v", audit, err)
	}
	query.Hour, query.Search = nil, "23:30"
	audit, err = l.WorkspaceUsage(query)
	if err != nil || audit.Total != 1 || audit.Groups[0].Day != "2026-11-14" {
		t.Fatalf("local search: %+v %v", audit, err)
	}
	after, err := l.Configuration()
	if err != nil || !reflect.DeepEqual(config, after) {
		t.Fatalf("configuration changed: %+v %v", after, err)
	}
}

func TestWorkspaceViewingTimezoneDSTAndFractionalOffset(t *testing.T) {
	for _, tc := range []struct {
		zone, now, day string
		hour           int
		calls          []string
		expected       int
	}{
		{"America/New_York", "2026-11-01T08:00:00Z", "2026-11-01", 1, []string{"2026-11-01T05:15:00Z", "2026-11-01T06:15:00Z"}, 2},
		{"Asia/Kolkata", "2026-11-14T01:00:00Z", "2026-11-14", 0, []string{"2026-11-13T18:45:00Z"}, 1},
		{"Australia/Lord_Howe", "2026-04-04T17:00:00Z", "2026-04-05", 1, []string{"2026-04-04T14:45:00Z", "2026-04-04T15:15:00Z", "2026-04-04T15:45:00Z"}, 2},
	} {
		t.Run(tc.zone, func(t *testing.T) {
			l := newLedger(t)
			if err := l.Configure(testConfiguration(nil)); err != nil {
				t.Fatal(err)
			}
			for _, at := range tc.calls {
				instant, _ := time.Parse(time.RFC3339, at)
				l.now = func() time.Time { return instant }
				call, err := l.Admit("main", "fixture", "", "")
				if err != nil {
					t.Fatal(err)
				}
				if err = l.Settle(call, &Usage{Input: 1, Output: 1}, 200, "", false); err != nil {
					t.Fatal(err)
				}
			}
			now, _ := time.Parse(time.RFC3339, tc.now)
			l.now = func() time.Time { return now }
			q := UsageQuery{View: "audit", Days: 1, Page: 1, Timezone: tc.zone, Day: tc.day, Hour: &tc.hour}
			result, err := l.WorkspaceUsage(q)
			if err != nil || result.Total != tc.expected || len(result.Groups) != 1 || result.Groups[0].Day != tc.day {
				t.Fatalf("viewing zone: %+v %v", result, err)
			}
		})
	}
}

func TestWorkspaceRejectsUnknownViewingTimezone(t *testing.T) {
	for _, zone := range []string{"Local", "wrong/timezone"} {
		if _, err := workspaceQuery(url.Values{"view": {"overview"}, "timezone": {zone}}); err == nil {
			t.Fatal("accepted", zone)
		}
	}
}

func TestWorkspaceViewingTimezoneRetainsArchivedAccountingDates(t *testing.T) {
	l := newLedger(t)
	if err := l.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	call, err := l.Admit("main", "fixture", "", "")
	if err != nil {
		t.Fatal(err)
	}
	if err = l.Settle(call, &Usage{Input: 100, Output: 20}, 200, "", false); err != nil {
		t.Fatal(err)
	}
	later := l.now().Add(49 * time.Hour)
	l.now = func() time.Time { return later }
	if err = l.Compact(); err != nil {
		t.Fatal(err)
	}
	q := UsageQuery{View: "overview", Days: 7, Page: 1, Timezone: "America/Los_Angeles", Day: call.Day}
	result, err := l.WorkspaceUsage(q)
	if err != nil || result.Archived != 1 || !result.DailyAggregated || len(result.Hourly) != 0 || len(result.Groups) != 1 || result.Groups[0].Day != call.Day || result.AccountingTimezone != "UTC" {
		t.Fatalf("archive conversion invented timestamps: %+v %v", result, err)
	}
}
