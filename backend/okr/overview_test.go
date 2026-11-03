package okr

import "testing"

func TestOverviewKeepsSourceDatesAndFirstBaseline(t *testing.T) {
	w := Workspace{Config: Config{StartDate: "2026-11-01", Metrics: []Metric{{ID: "stars", Source: "github", SourceKey: "github:7:stars"}}, KeyResults: []KeyResult{{ID: "growth", MetricID: "stars", DueDate: "2026-11-03"}}}}
	for i, o := range []Observation{
		{Date: "2026-11-01", Value: 10}, {Date: "2026-11-01", Value: 12},
		{Date: "2026-11-03", Value: 18}, {Date: "2026-11-02", Value: 16},
		{Date: "2026-11-03", Value: 17}, {Date: "2026-11-04", Value: 100},
	} {
		o.MetricID, o.Source, o.SourceKey = "stars", "github", "github:7:stars"
		if i == 5 {
			o.SourceKey = "github:old:stars"
		}
		w.Observations = append(w.Observations, o)
	}
	r := overview(w).KeyResults[0]
	if r.Baseline.Value != 10 || r.Latest.Value != 17 || r.Delta == nil || *r.Delta != 1 {
		t.Fatal(r)
	}
	w.Observations = append(w.Observations, Observation{MetricID: "stars", Source: "github", SourceKey: "github:7:stars", Date: "2026-11-04", Value: 200})
	if overview(w).KeyResults[0].Latest.Value != 17 {
		t.Fatal("post-deadline data changed the KR")
	}
	w.Observations = w.Observations[:2]
	if overview(w).KeyResults[0].Delta != nil {
		t.Fatal("first-day baseline became daily zero")
	}
}
