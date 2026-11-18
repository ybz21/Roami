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

func TestPreparedContinuationPinsOriginalProviderAndModelAcrossRounds(t *testing.T) {
	yes := true
	binding := SessionBinding{ID: "session", ProviderID: "provider", Directory: "/project", PID: 11, Processes: map[int]string{11: "root"}}
	initial := Spec{Key: "prepared", Executor: "claude", Model: "free", Persistent: true}
	current := Spec{Key: "work-round-2", Executor: "claude", SessionID: "session", PreparedFrom: "prepared"}
	state := sessionLifecycle{Executor: "claude", Model: "free", Binding: binding, CompletedKey: "work-round-1"}
	receipt := Receipt{Session: "session", Binding: &binding, Workspace: &Workspace{Directory: "/project"}}
	result := Result{State: "succeeded", InputStopped: &yes, OutcomeKnown: &yes}
	if !preparedOriginMatches(current, state, initial, receipt, result) {
		t.Fatal("later round lost original provider")
	}
	for _, change := range []string{"model", "provider", "pid", "executor", "session", "unsettled"} {
		t.Run(change, func(t *testing.T) {
			a, b, c, d, e := current, state, initial, receipt, result
			switch change {
			case "model":
				b.Model = "paid"
			case "provider":
				b.Binding.ProviderID = "other"
			case "pid":
				b.Binding.PID = 12
			case "executor":
				a.Executor = "codex"
			case "session":
				a.SessionID = "other"
			case "unsettled":
				e.OutcomeKnown = nil
			}
			if preparedOriginMatches(a, b, c, d, e) {
				t.Fatal("changed binding accepted")
			}
		})
	}
}

func TestPreparedSelectionAcceptsSettledHandoffWithoutReplacingOriginalInstance(t *testing.T) {
	yes := true
	b := SessionBinding{ID: "session", ProviderID: "provider", Directory: "/project", PID: 11, Processes: map[int]string{11: "root"}}
	initial := Spec{Key: "initial", Executor: "claude", Model: "free", Persistent: true}
	receipt := Receipt{Session: "session", Binding: &b, Workspace: &Workspace{Directory: "/project"}}
	state := sessionLifecycle{Executor: "claude", Model: "free", Binding: b, State: "idle", CompletedKey: "handoff"}
	done := Result{State: "succeeded", InputStopped: &yes, OutcomeKnown: &yes}
	proof := preparedTurnProof{Spec: Spec{Key: "handoff", Executor: "claude", SessionID: "session"}, Receipt: receipt, Result: done}
	state.Binding.Processes = map[int]string{11: "root", 12: "stdio-host"}
	currentBinding := state.Binding
	proof.Receipt.Binding = &currentBinding
	if _, err := preparedSelection("initial", initial, receipt, state, done, proof); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"missing stop", "unknown outcome", "wrong provider", "wrong key", "wrong session", "ended", "conflict"} {
		t.Run(name, func(t *testing.T) {
			p, l := proof, state
			switch name {
			case "missing stop":
				p.Result.InputStopped = nil
			case "unknown outcome":
				p.Result.OutcomeKnown = nil
			case "wrong provider":
				l.Binding.ProviderID = "other"
			case "wrong key":
				p.Spec.Key = "other"
			case "wrong session":
				p.Spec.SessionID = "other"
			case "ended":
				l.EndedIdle = true
			case "conflict":
				l.UnknownReason = "SESSION_COMPLETION_MISMATCH"
			}
			if _, err := preparedSelection("initial", initial, receipt, l, done, p); err == nil {
				t.Fatal("unconfirmed handoff accepted")
			}
		})
	}
}
