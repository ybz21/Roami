package agentexecution

import (
	"os"
	"os/exec"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func cancellationSleep(t *testing.T) *exec.Cmd {
	t.Helper()
	child := exec.Command("sleep", "60")
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = child.Process.Kill(); _ = child.Wait() })
	return child
}

func TestSessionCancelStopsCapturedToolsButPreservesBaselineAndLaterChildren(t *testing.T) {
	s, binding := sessionFixture(t)
	baseline := cancellationSleep(t)
	seedSession(t, s, binding)
	spec, _ := startSessionTask(t, s, binding, "tool-cancel")
	tool := cancellationSleep(t)
	keys := cancellationKeyLog(t, s, false)
	status, err := s.Cancel(spec.Key)
	if err != nil || status.State != "cancelling" || status.Result != nil || status.ObservationErrorCode != "" {
		t.Fatalf("cancel: %+v %v", status, err)
	}
	stopped := make(chan error, 1)
	go func() { stopped <- tool.Wait() }()
	select {
	case err := <-stopped:
		if err == nil {
			t.Fatal("captured tool finished instead of stopping")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("captured tool was not stopped")
	}
	dir, _ := s.directory(spec.Key)
	var intent sessionInterrupt
	if err := readJSON(filepath.Join(dir, "interrupt-request.json"), &intent); err != nil || intent.Tools[tool.Process.Pid] == "" || intent.Tools[baseline.Process.Pid] != "" || !intent.ToolSignalsDelivered {
		t.Fatalf("missing bounded tool interrupt journal: %+v %v", intent, err)
	}
	future := cancellationSleep(t)
	if _, err := s.Cancel(spec.Key); err != nil {
		t.Fatal(err)
	}
	for _, child := range []*exec.Cmd{baseline, future} {
		if err := child.Process.Signal(syscall.Signal(0)); err != nil {
			t.Fatalf("unowned child stopped: %d %v", child.Process.Pid, err)
		}
	}
	input, _ := os.ReadFile(keys)
	if string(input) != "send-keys -t %3 Escape\n" {
		t.Fatalf("interrupt replayed: %s", input)
	}
}

func TestCapturedToolSignalsRequireScopeAncestryAndStartToken(t *testing.T) {
	for _, mode := range []string{"reused-pid", "foreign-scope", "foreign-process", "baseline", "unrelated-parent"} {
		t.Run(mode, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedSession(t, s, binding)
			spec, _ := startSessionTask(t, s, binding, "safe-tool-signal")
			status, err := s.Status(spec.Key)
			if err != nil {
				t.Fatal(err)
			}
			owned := *status.Binding
			child := cancellationSleep(t)
			token := observedProcessToken(child.Process.Pid)
			switch mode {
			case "reused-pid":
				token = "stale"
			case "foreign-scope":
				owned.Scope = "/some/other/scope"
			case "foreign-process":
				if owned.ForeignProcesses == nil {
					owned.ForeignProcesses = map[int]string{}
				}
				owned.ForeignProcesses[child.Process.Pid] = token
			case "baseline":
				owned.Processes[child.Process.Pid] = token
			case "unrelated-parent":
				otherPane := cancellationSleep(t)
				owned.PID = otherPane.Process.Pid
				owned.Processes = map[int]string{owned.PID: observedProcessToken(owned.PID)}
			}
			_ = signalCapturedSessionTools(owned, map[int]string{child.Process.Pid: token})
			if err := child.Process.Signal(syscall.Signal(0)); err != nil {
				t.Fatalf("unsafe %s signal: %v", mode, err)
			}
		})
	}
}

func TestSessionCancelNeverSignalsToolsAfterManualInput(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	spec, _ := startSessionTask(t, s, binding, "manual-tool-turn")
	child := cancellationSleep(t)
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: "provider-thread", TurnID: "manual-turn", Prompt: "new user work"}); err != nil {
		t.Fatal(err)
	}
	status, err := s.Cancel(spec.Key)
	if err != nil || status.State != "unknown" || status.Result != nil {
		t.Fatalf("new turn accepted: %+v %v", status, err)
	}
	if err := child.Process.Signal(syscall.Signal(0)); err != nil {
		t.Fatal("new user work was stopped", err)
	}
}

func TestSessionCancelDoesNotReplayUncertainToolSignals(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	spec, _ := startSessionTask(t, s, binding, "uncertain-tool-signal")
	status, err := s.Status(spec.Key)
	if err != nil {
		t.Fatal(err)
	}
	child := cancellationSleep(t)
	dir, _ := s.directory(spec.Key)
	path, _ := s.lifecycleFile(binding)
	var state sessionLifecycle
	if err := readJSON(path, &state); err != nil {
		t.Fatal(err)
	}
	intent := sessionInterrupt{ResourceID: status.Binding.resourceID(), ProviderID: state.Binding.ProviderID, TurnID: state.TurnID, PromptHash: state.PromptHash, Delivered: true, Tools: map[int]string{child.Process.Pid: observedProcessToken(child.Process.Pid)}}
	if err := writeJSON(filepath.Join(dir, "interrupt-request.json"), intent); err != nil {
		t.Fatal(err)
	}
	keys := cancellationKeyLog(t, s, false)
	status, err = s.Cancel(spec.Key)
	if err != nil || status.ObservationErrorCode != "SESSION_TOOL_INTERRUPT_UNKNOWN" || status.Result != nil {
		t.Fatalf("uncertain signal replayed: %+v %v", status, err)
	}
	if err := child.Process.Signal(syscall.Signal(0)); err != nil {
		t.Fatal("uncertain signal replayed", err)
	}
	if input, _ := os.ReadFile(keys); len(input) != 0 {
		t.Fatalf("Escape replayed: %s", input)
	}
}
