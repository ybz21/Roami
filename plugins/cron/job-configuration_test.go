package cron

import (
	"testing"
	"time"
)

func TestDisabledJobUsesExplicitTimezoneAndPreservesStateOnEdit(t *testing.T) {
	args := map[string]string{"name": "daily-main", "cron": "0 9 * * *", "action": "exec", "command": "python3 wake_main.py", "enabled": "false", "timezone": "Asia/Shanghai"}
	now := time.Date(2026, 11, 5, 23, 0, 0, 0, time.UTC)
	job, err := configuredJob(args, nil, now)
	if err != nil || job.Enabled || job.NextRun != time.Date(2026, 11, 6, 1, 0, 0, 0, time.UTC).Unix() {
		t.Fatalf("%+v %v", job, err)
	}
	job.Runs = 3
	job.LastRun = now.Unix()
	delete(args, "enabled")
	delete(args, "timezone")
	args["cron"] = "0 18 * * *"
	edited, err := configuredJob(args, &job, now)
	if err != nil || edited.Enabled || edited.Timezone != "Asia/Shanghai" || edited.Runs != 3 || edited.LastRun != job.LastRun || edited.NextRun != time.Date(2026, 11, 6, 10, 0, 0, 0, time.UTC).Unix() {
		t.Fatalf("%+v %v", edited, err)
	}
	view := jobView(edited)
	if view["timezone"] != "Asia/Shanghai" || view["nextRunAt"] != "2026-11-06 18:00:00" {
		t.Fatal(view)
	}
	args["enabled"] = "true"
	if _, err = configuredJob(args, &job, now); err == nil {
		t.Fatal("editing silently enabled a disabled job")
	}
}

func TestJobConfigurationRejectsUnknownTimezoneAndKeepsLegacyDefaults(t *testing.T) {
	args := map[string]string{"name": "legacy", "cron": "0 9 * * *", "prompt": "Run the agreed work"}
	now := time.Date(2026, 11, 5, 8, 0, 0, 0, time.Local)
	job, err := configuredJob(args, nil, now)
	if err != nil || !job.Enabled || job.Timezone != "" || job.NextRun != time.Date(2026, 11, 5, 9, 0, 0, 0, time.Local).Unix() {
		t.Fatalf("%+v %v", job, err)
	}
	for _, change := range []map[string]string{{"timezone": "Wrong/Zone"}, {"enabled": "maybe"}} {
		edited := map[string]string{}
		for k, v := range args {
			edited[k] = v
		}
		for k, v := range change {
			edited[k] = v
		}
		if _, err := configuredJob(edited, nil, now); err == nil {
			t.Fatal("invalid schedule accepted", change)
		}
	}
}

func TestDailyTimezoneSkipsMissingWallClockHour(t *testing.T) {
	job := Job{Cron: "30 2 * * *", Timezone: "America/New_York"}
	next, err := nextRun(job, time.Date(2026, 3, 8, 6, 59, 0, 0, time.UTC))
	if err != nil || next.UTC() != time.Date(2026, 3, 9, 6, 30, 0, 0, time.UTC) {
		t.Fatal(next, err)
	}
}
