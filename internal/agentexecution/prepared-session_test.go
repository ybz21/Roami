package agentexecution

import (
	"strings"
	"testing"
)

func TestPreparedSessionExposesOnlySettledRouteRefusalFromSamePreparedMain(t *testing.T) {
	yes := true
	binding := SessionBinding{ID: "session", ProviderID: "provider", Directory: "/project", PID: 11, Processes: map[int]string{11: "root"}}
	initial := Spec{Key: "prepared", Executor: "claude", Model: "free", Persistent: true}
	receipt := Receipt{Session: binding.ID, Binding: &binding, Workspace: &Workspace{Directory: "/project"}}
	prepared := Result{State: "succeeded", InputStopped: &yes, OutcomeKnown: &yes}
	key := "project-main:" + strings.Repeat("a", 32) + ":" + strings.Repeat("b", 24)
	digest := strings.Repeat("c", 64)
	for _, scenario := range []string{"compaction", "route", "retry", "context rejected", "unknown", "wrong prepared", "different launch", "invalid retry", "missing digest"} {
		t.Run(scenario, func(t *testing.T) {
			state := sessionLifecycle{Executor: "claude", Model: "free", Binding: binding, State: "idle", CompletedKey: key}
			later := preparedTurnProof{
				Spec:    Spec{Key: key, Executor: "claude", SessionID: binding.ID, PreparedFrom: initial.Key, Persistent: true},
				Receipt: receipt,
				Result:  Result{State: "failed", ErrorCode: "CLAUDE_COMPACTION_FAILED", InputStopped: &yes, OutcomeKnown: &yes, FinishedMS: 2, StopEvidence: digest},
			}
			switch scenario {
			case "route":
				later.Result.ErrorCode = "MODEL_ROUTE_NO_AVAILABLE_MEMBER"
			case "context rejected":
				state.CompletedKey = "native-conversation:test"
				later.Spec.Key = state.CompletedKey
				later.Result.ErrorCode = "CLAUDE_COMPACTION_INPUT_REJECTED"
			case "retry":
				state.CompletedKey += ":retry-4"
				later.Spec.Key = state.CompletedKey
			case "unknown":
				later.Result.ErrorCode = "CLAUDE_API_REQUEST_FAILED"
			case "wrong prepared":
				later.Spec.PreparedFrom = "other"
			case "different launch":
				state.CompletedKey += ":resume-1"
				later.Spec.Key = state.CompletedKey
			case "invalid retry":
				state.CompletedKey += ":retry-0"
				later.Spec.Key = state.CompletedKey
			case "missing digest":
				later.Result.StopEvidence = ""
			}
			selected, err := preparedSelection(initial.Key, initial, receipt, state, prepared, later)
			if err != nil || !selected.Ready {
				t.Fatalf("readiness changed: %+v %v", selected, err)
			}
			want := PreparedRefusal{LaunchKey: state.CompletedKey, Code: later.Result.ErrorCode, FinishedMS: 2, StopEvidence: digest}
			if scenario == "context rejected" {
				if selected.RouteRefusal != nil || selected.ContextRejection == nil || *selected.ContextRejection != want {
					t.Fatalf("wrong context proof: %+v", selected)
				}
				return
			}
			if selected.ContextRejection != nil {
				t.Fatalf("unexpected context rejection: %+v", selected.ContextRejection)
			}
			if scenario != "compaction" && scenario != "route" && scenario != "retry" {
				if selected.RouteRefusal != nil {
					t.Fatalf("unexpected route refusal: %+v", selected.RouteRefusal)
				}
				return
			}
			if selected.RouteRefusal == nil || *selected.RouteRefusal != want {
				t.Fatalf("missing route refusal: %+v", selected.RouteRefusal)
			}
		})
	}
}

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

func TestPreparedRecoveryPinsSourceAndConfiguredModelAcrossRounds(t *testing.T) {
	yes := true
	binding := SessionBinding{ID: "recovered", ProviderID: "provider", Directory: "/project", PID: 11, Processes: map[int]string{11: "root"}}
	spec := Spec{Key: "recovery", Executor: "claude", Model: "gateway-vision", Persistent: true, SessionID: "old", ResumeFrom: "old-turn", ResumeProvider: binding.ProviderID}
	receipt := Receipt{Session: binding.ID, Binding: &binding, Workspace: &Workspace{Directory: "/project"}, RecoveredFrom: spec.ResumeFrom, ConfiguredModel: spec.Model}
	state := sessionLifecycle{Executor: "claude", Model: spec.Model, Binding: binding, State: "idle", CompletedKey: spec.Key}
	done := Result{State: "succeeded", InputStopped: &yes, OutcomeKnown: &yes}
	current := Spec{Key: "following", Executor: spec.Executor, SessionID: binding.ID, PreparedFrom: spec.Key}
	prepared, err := preparedSelection(spec.Key, spec, receipt, state, done)
	if err != nil || prepared.RecoveredFrom != spec.ResumeFrom || prepared.ConfiguredModel != spec.Model || !prepared.Ready {
		t.Fatalf("recovered readiness: %+v %v", prepared, err)
	}
	if !preparedOriginMatches(current, state, spec, receipt, done) {
		t.Fatal("verified recovery could not continue")
	}
	for _, mutation := range []func(*Spec, *Receipt){
		func(spec *Spec, _ *Receipt) { spec.ResumeProvider = "other-provider" },
		func(spec *Spec, _ *Receipt) { spec.SessionID = receipt.Session },
		func(_ *Spec, receipt *Receipt) { receipt.ConfiguredModel = "other-model" },
		func(_ *Spec, receipt *Receipt) { receipt.RecoveredFrom = "other-turn" },
	} {
		candidate, proof := spec, receipt
		mutation(&candidate, &proof)
		if _, err := preparedSelection(spec.Key, candidate, proof, state, done); err == nil || preparedOriginMatches(current, state, candidate, proof, done) {
			t.Fatal("changed recovery evidence accepted")
		}
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
