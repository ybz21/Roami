package cron

import (
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

func TestScopedTickOnlyDispatchesNamedDueJobs(t *testing.T) {
	now := time.Date(2026, 11, 6, 1, 0, 0, 0, time.UTC)
	jobs := []Job{
		{Name: "okr-kickoff", Cron: "0 9 * * *", Timezone: "Asia/Shanghai", Enabled: true, NextRun: now.Unix(), Action: "exec"},
		{Name: "okr-review", Cron: "0 21 * * *", Timezone: "Asia/Shanghai", Enabled: true, NextRun: now.Add(time.Hour).Unix(), Action: "exec"},
		{Name: "other-project", Cron: "* * * * *", Enabled: true, NextRun: now.Add(-time.Minute).Unix(), Runs: 7, LastRun: 100},
		{Name: "okr-kickoff-copy", Cron: "* * * * *", Enabled: true, NextRun: now.Unix()},
	}
	before := append([]Job(nil), jobs...)
	scope, err := schedulerScope(map[string]string{"names": `["okr-kickoff","okr-review"]`})
	if err != nil {
		t.Fatal(err)
	}
	var dispatched []string
	fired, changed, err := tickJobs(jobs, scope, now, func(job *Job) error {
		dispatched = append(dispatched, job.Name)
		return nil
	})
	if err != nil || !changed || !reflect.DeepEqual(fired, []string{"okr-kickoff"}) || !reflect.DeepEqual(dispatched, fired) {
		t.Fatalf("fired=%v dispatched=%v changed=%v err=%v", fired, dispatched, changed, err)
	}
	if jobs[0].NextRun != now.Add(24*time.Hour).Unix() || !reflect.DeepEqual(jobs[1:], before[1:]) {
		t.Fatalf("unexpected schedule mutation: %+v", jobs)
	}
}

func TestMissingScopeNameRejectsBeforeAnyDispatchOrMutation(t *testing.T) {
	now := time.Now()
	jobs := []Job{{Name: "known", Cron: "* * * * *", Enabled: true, NextRun: now.Unix()}}
	before := append([]Job(nil), jobs...)
	scope, err := schedulerScope(map[string]string{"names": `["known","missing"]`})
	if err != nil {
		t.Fatal(err)
	}
	dispatched := false
	fired, changed, err := tickJobs(jobs, scope, now, func(*Job) error { dispatched = true; return nil })
	if !errors.Is(err, errJobScopeNotFound) || changed || dispatched || len(fired) != 0 || !reflect.DeepEqual(jobs, before) {
		t.Fatalf("fired=%v changed=%v dispatched=%v err=%v jobs=%+v", fired, changed, dispatched, err, jobs)
	}
}

func TestInvalidScopeCannotFallBackToGlobalTickOrServe(t *testing.T) {
	for _, raw := range []string{"", "null", `[]`, `"job"`, `["job",1]`, `[""]`, `[" job"]`, `["job","job"]`} {
		for name, handler := range map[string]sdk.CommandHandler{"tick": tick, "serve": serve} {
			t.Run(name+"/"+raw, func(t *testing.T) {
				_, err := handler(&sdk.Ctx{}, map[string]string{"names": raw})
				if err == nil || !strings.HasPrefix(err.Error(), "INVALID_CRON_JOB_SCOPE:") {
					t.Fatalf("scope reached host dispatch: %v", err)
				}
			})
		}
	}
}

func TestUnscopedTickKeepsExistingGlobalBehavior(t *testing.T) {
	now := time.Now()
	jobs := []Job{
		{Name: "first", Cron: "* * * * *", Enabled: true, NextRun: now.Unix()},
		{Name: "second", Cron: "* * * * *", Enabled: true, NextRun: now.Unix()},
		{Name: "disabled", Cron: "* * * * *", Enabled: false, NextRun: now.Unix()},
	}
	scope, err := schedulerScope(nil)
	if err != nil || scope != nil {
		t.Fatal(scope, err)
	}
	fired, changed, err := tickJobs(jobs, scope, now, func(*Job) error { return nil })
	if err != nil || !changed || !reflect.DeepEqual(fired, []string{"first", "second"}) || jobs[2].NextRun != now.Unix() {
		t.Fatal(fired, changed, err, jobs)
	}
}

func TestSingleScopeAndFlagTyposCannotBecomeGlobal(t *testing.T) {
	scope, err := schedulerScope(map[string]string{"name": "exact-name", "json": "true"})
	if err != nil || len(scope) != 1 || !scope["exact-name"] {
		t.Fatal(scope, err)
	}
	for _, args := range []map[string]string{
		{"name": ""},
		{"namess": `["exact-name"]`},
		{"name": "exact-name", "names": `["exact-name"]`},
	} {
		if _, err := tick(&sdk.Ctx{}, args); err == nil || !strings.HasPrefix(err.Error(), "INVALID_CRON_JOB_SCOPE:") {
			t.Fatalf("scope reached host dispatch: %v", err)
		}
	}
}
