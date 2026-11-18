package agentexecution

import "testing"

func TestPreparedSelectionRequiresOriginalConfiguredModelAndKnownIdleStop(t *testing.T) {
	yes := true
	binding := SessionBinding{ID: "original-session", Name: "original-session", ProviderID: "original-provider", Directory: "/project", PID: 10, Processes: map[int]string{10: "start"}}
	spec := Spec{Key: "prepare-1", Executor: "claude", Model: "free", Persistent: true, Directory: "/project"}
	receipt := Receipt{Session: binding.ID, Binding: &binding, Workspace: &Workspace{Directory: "/project"}}
	state := sessionLifecycle{Executor: "claude", Model: "free", Binding: binding, State: "idle", CompletedKey: "prepare-1", Tools: map[string]bool{}}
	result := Result{State: "succeeded", InputStopped: &yes, OutcomeKnown: &yes}
	good, err := preparedSelection(spec.Key, spec, receipt, state, result)
	if err != nil || good.ConfiguredModel != "free" || good.SessionID != binding.ID || !good.Ready {
		t.Fatalf("selection %+v %v", good, err)
	}
	for _, tc := range []struct {
		name   string
		change func(*Spec, *Receipt, *sessionLifecycle, *Result)
	}{
		{"session changed", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { r.Session = "different" }},
		{"model changed", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { l.Model = "paid" }},
		{"provider changed", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { l.Binding.ProviderID = "different" }},
		{"new turn", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { l.LaunchKey = "later" }},
		{"stale key", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { l.CompletedKey = "later" }},
		{"pending tool", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { l.Tools = map[string]bool{"tool": true} }},
		{"busy", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { l.State = "busy" }},
		{"unknown stop", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { v.InputStopped = nil }},
		{"unknown outcome", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { v.OutcomeKnown = nil }},
		{"failed", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { v.State = "failed" }},
		{"not initial", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { s.SessionID = "old" }},
		{"not persistent", func(s *Spec, r *Receipt, l *sessionLifecycle, v *Result) { s.Persistent = false }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			a, b, c, d := spec, receipt, state, result
			tc.change(&a, &b, &c, &d)
			if _, err := preparedSelection(spec.Key, a, b, c, d); err == nil {
				t.Fatal("unconfirmed selection accepted")
			}
		})
	}
}
