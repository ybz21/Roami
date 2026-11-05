package agentexecution

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestProviderProcessesGoneRejectsSurvivingAndUnknownWriters(t *testing.T) {
	binding := SessionBinding{PID: 100, Processes: map[int]string{100: "root", 101: "worker"}}
	for _, sample := range []struct {
		name      string
		processes map[int]paneProcess
		scope     []int
		want      bool
	}{
		{"gone", map[int]paneProcess{}, nil, true},
		{"recycled root", map[int]paneProcess{100: {Token: "new"}}, nil, true},
		{"root alive", map[int]paneProcess{100: {Token: "root"}}, nil, false},
		{"orphan alive", map[int]paneProcess{101: {Token: "worker"}}, nil, false},
		{"unknown scoped process", map[int]paneProcess{}, []int{500}, false},
	} {
		t.Run(sample.name, func(t *testing.T) {
			if got := providerProcessesGone(binding, sample.processes, sample.scope); got != sample.want {
				t.Fatalf("stopped=%v", got)
			}
		})
	}
	binding.Processes = nil
	if providerProcessesGone(binding, map[int]paneProcess{}, nil) {
		t.Fatal("missing root proof was accepted")
	}
}

func TestProviderRecoveryRejectsGuessedOrChangedSourceBeforeObservingProcesses(t *testing.T) {
	s := testService(t)
	directory := t.TempDir()
	workspace, err := s.rememberWorkspace(Workspace{Directory: directory})
	if err != nil {
		t.Fatal(err)
	}
	binding := SessionBinding{ID: "old", Name: "old", ProviderID: completionThread, Directory: directory, HostProof: sessionHostProof(), DirectoryProof: sessionDirectoryProof(directory)}
	prior := Spec{Key: "original", Executor: "codex", Persistent: true, Directory: directory, Prompt: "original input"}
	dir, _ := s.directory(prior.Key)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	state := sessionLifecycle{Binding: binding, Workspace: &workspace, Executor: "codex", State: "idle", CompletedKey: prior.Key, TurnID: "turn-1", PromptHash: workspaceHash(sessionPrompt(dir, prior)), Tools: map[string]bool{}}
	base := providerRecoverySource{Spec: prior, Receipt: Receipt{Session: binding.ID, Workspace: &workspace, Binding: &binding}, Lifecycle: state}
	spec := Spec{Key: "next", Executor: "codex", Persistent: true, SessionID: binding.ID, ResumeFrom: prior.Key, ResumeProvider: completionThread, Prompt: "next"}
	for _, sample := range []struct {
		name   string
		change func(*providerRecoverySource, *Spec)
		code   string
	}{
		{"other executor", func(_ *providerRecoverySource, v *Spec) { v.Executor = "claude" }, "SESSION_RECOVERY_BINDING_CONFLICT"},
		{"other provider", func(_ *providerRecoverySource, v *Spec) { v.ResumeProvider = "00000000-0000-4000-8000-000000000002" }, "SESSION_RECOVERY_BINDING_CONFLICT"},
		{"missing provider", func(_ *providerRecoverySource, v *Spec) { v.ResumeProvider = "" }, "SESSION_RECOVERY_BINDING_CONFLICT"},
		{"other session", func(_ *providerRecoverySource, v *Spec) { v.SessionID = "other" }, "SESSION_RECOVERY_BINDING_CONFLICT"},
		{"stale completion", func(v *providerRecoverySource, _ *Spec) { v.Lifecycle.CompletedKey = "newer" }, "SESSION_RECOVERY_SOURCE_CHANGED"},
		{"manual turn", func(v *providerRecoverySource, _ *Spec) { v.Lifecycle.PromptHash = "manual" }, "SESSION_RECOVERY_SOURCE_CHANGED"},
		{"tools pending", func(v *providerRecoverySource, _ *Spec) { v.Lifecycle.Tools = map[string]bool{"write": true} }, "SESSION_RECOVERY_SOURCE_CHANGED"},
		{"unknown lifecycle", func(v *providerRecoverySource, _ *Spec) { v.Lifecycle.State = "unknown" }, "SESSION_RECOVERY_SOURCE_CHANGED"},
		{"missing stop result", func(_ *providerRecoverySource, _ *Spec) {}, "SESSION_RECOVERY_OUTCOME_UNRESOLVED"},
	} {
		t.Run(sample.name, func(t *testing.T) {
			source, request := base, spec
			sample.change(&source, &request)
			_, err := s.providerRecovery(context.Background(), request, source)
			if err == nil || err.Error() != sample.code {
				t.Fatalf("err=%v", err)
			}
		})
	}
	for _, result := range []Result{{State: "unknown"}, {State: "succeeded"}, {State: "succeeded", InputStopped: boolPointer(true), OutcomeKnown: boolPointer(false)}} {
		if err := writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
			t.Fatal(err)
		}
		if _, err := s.providerRecovery(context.Background(), spec, base); err == nil || err.Error() != "SESSION_RECOVERY_OUTCOME_UNRESOLVED" {
			t.Fatalf("unknown result accepted: %v", err)
		}
	}
	if err := writeJSON(filepath.Join(dir, "closed.json"), Status{}); err != nil {
		t.Fatal(err)
	}
	if _, err := s.providerRecovery(context.Background(), spec, base); err == nil || err.Error() != "SESSION_RECOVERY_EXPLICITLY_CLOSED" {
		t.Fatalf("closed source accepted: %v", err)
	}
}

func boolPointer(value bool) *bool { return &value }

func TestProviderRecoveryWorkspaceNeverSubstitutesAnotherRegistryEntry(t *testing.T) {
	s := testService(t)
	saved, err := s.rememberWorkspace(Workspace{Directory: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	got, err := s.recoveryWorkspace(context.Background(), saved)
	if err != nil || !reflect.DeepEqual(got, saved) {
		t.Fatalf("workspace=%+v %v", got, err)
	}
	changed := saved
	changed.Directory = t.TempDir()
	if _, err := s.recoveryWorkspace(context.Background(), changed); err == nil {
		t.Fatal("different directory accepted")
	}
	changed = saved
	changed.ProjectID = "other"
	if _, err := s.recoveryWorkspace(context.Background(), changed); err == nil {
		t.Fatal("different project accepted")
	}
}

func TestProviderRecoveryThroughRealPythonAndGoCLI(t *testing.T) {
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv required")
	}
	sessionFixture(t)
	repository, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	recordRuntimeSources(t, repository, "provider_recovery_scenario.py", "persistent_provider.py")
	root := t.TempDir()
	binary := filepath.Join(root, "roami")
	build := exec.Command("go", "build", "-o", binary, "./cmd/roami")
	build.Dir = repository
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, output)
	}
	instance := filepath.Join(root, "instance")
	launcher := filepath.Join(repository, "scripts/dev/isolated-roami.sh")
	t.Cleanup(func() {
		if output, err := exec.Command(launcher, instance, "--stop").CombinedOutput(); err != nil {
			t.Logf("cleanup: %v %s", err, output)
		}
	})
	command := exec.Command(launcher, instance, "uv", "run", "--frozen", "--directory", filepath.Join(repository, "agent-runtime"), "python", "tests/provider_recovery_scenario.py", binary, instance)
	command.Dir = repository
	if output, err := command.CombinedOutput(); err != nil || !strings.Contains(string(output), "provider recovery scenario passed") {
		t.Fatalf("recovery: %v\n%s", err, output)
	}
}

func TestResumedCodexCannotAdoptAnotherProviderFromInitialInput(t *testing.T) {
	s, binding := sessionFixture(t)
	binding.ProviderID = completionThread
	state := sessionLifecycle{Binding: binding, Executor: "codex", State: "submitting", LaunchKey: "restore", InitialLaunch: true, Resuming: true, Tools: map[string]bool{}}
	path, err := s.lifecycleFile(binding)
	if err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	dir, _ := s.directory("restore")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	spec := Spec{Key: "restore", Executor: "codex", Persistent: true, SessionID: "original", ResumeFrom: "previous", ResumeProvider: completionThread, Prompt: "continue"}
	if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), Receipt{Session: binding.ID, Workspace: &Workspace{Directory: binding.Directory}}); err != nil {
		t.Fatal(err)
	}
	event := SessionEvent{Hook: "UserPromptSubmit", ProviderID: "00000000-0000-4000-8000-000000000002", TurnID: "wrong-turn", Prompt: sessionPrompt(dir, spec)}
	if err := s.applySessionEvent("codex", binding, event); err != nil {
		t.Fatal(err)
	}
	if err := readJSON(path, &state); err != nil || state.State != "unknown" || state.Binding.ProviderID != completionThread {
		t.Fatalf("changed provider accepted: %+v %v", state, err)
	}
	event.ProviderID = completionThread
	if err := s.applySessionEvent("codex", binding, event); err != nil {
		t.Fatal(err)
	}
	var receipt Receipt
	if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil || receipt.Binding != nil {
		t.Fatalf("unknown resumed session was rebound: %+v %v", receipt, err)
	}
}

func TestRecoveryClaimCanOnlyAdvanceAfterProvenNoInputAndVanishedTerminal(t *testing.T) {
	s := testService(t)
	bin := filepath.Join(t.TempDir(), "tmux")
	if err := os.WriteFile(bin, []byte("#!/bin/sh\nexit 0\n"), 0700); err != nil {
		t.Fatal(err)
	}
	s.Runtime.TmuxBin = bin
	prior := Spec{Key: "failed-restore", Executor: "codex", Persistent: true, SessionID: "original-session", ResumeFrom: "original", ResumeProvider: completionThread, Prompt: "prior"}
	next := prior
	next.Key, next.Prompt = "next-restore", "next"
	root := t.TempDir()
	claim := filepath.Join(root, "recovery-claim.json")
	if got, err := s.availableRecoveryClaim(claim, next); err != nil || got != nil {
		t.Fatalf("empty claim=%+v %v", got, err)
	}
	if err := writeJSON(claim, prior); err != nil {
		t.Fatal(err)
	}
	dir, _ := s.directory(prior.Key)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "spec.json"), prior); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), Receipt{Session: "failed-unconfirmed-session"}); err != nil {
		t.Fatal(err)
	}
	for _, result := range []Result{
		{State: "unknown"},
		{State: "failed"},
		{State: "failed", ExecutionStarted: boolPointer(true), ExitCodeSource: "not_started", InputStopped: boolPointer(true), OutcomeKnown: boolPointer(true)},
		{State: "failed", ExecutionStarted: boolPointer(false), ExitCodeSource: "not_started", InputStopped: boolPointer(true), OutcomeKnown: boolPointer(false)},
	} {
		if err := writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
			t.Fatal(err)
		}
		if _, err := s.availableRecoveryClaim(claim, next); err == nil {
			t.Fatalf("unsafe claim advanced: %+v", result)
		}
	}
	known := Result{State: "failed", ExecutionStarted: boolPointer(false), ExitCodeSource: "not_started", InputStopped: boolPointer(true), OutcomeKnown: boolPointer(true)}
	if err := writeJSON(filepath.Join(dir, "result.json"), known); err != nil {
		t.Fatal(err)
	}
	if got, err := s.availableRecoveryClaim(claim, next); err != nil || got == nil || *got != prior {
		t.Fatalf("proven preinput retry: %+v %v", got, err)
	}
	next.ResumeProvider = "00000000-0000-4000-8000-000000000002"
	if _, err := s.availableRecoveryClaim(claim, next); err == nil {
		t.Fatal("another provider consumed claim")
	}
}

func TestRecoverySourceRequiresSameHostProfileAndCompleteOriginalTranscript(t *testing.T) {
	if sessionHostProof() == "" {
		t.Skip("host proof requires Linux proc namespaces")
	}
	s := testService(t)
	workspace, err := s.rememberWorkspace(Workspace{Directory: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	home := t.TempDir()
	binding := SessionBinding{ID: "old", Name: "old", PID: 1073741824, ProviderID: completionThread, Directory: workspace.Directory, HostProof: sessionHostProof(), DirectoryProof: sessionDirectoryProof(workspace.Directory), ProviderHome: home, ProviderHomeProof: sessionDirectoryProof(home), Scope: "/sys/fs/cgroup/roami-disposable-proof/tmux-spawn-00000000-0000-4000-8000-000000000001.scope", Processes: map[int]string{1073741824: "fixture-token"}}
	if !providerStopped(binding) {
		t.Skip("saved scope/proc proof unavailable")
	}
	prior := Spec{Key: "original", Executor: "codex", Persistent: true, Directory: workspace.Directory, Prompt: "original request"}
	dir, _ := s.directory(prior.Key)
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	result := Result{State: "succeeded", InputStopped: boolPointer(true), OutcomeKnown: boolPointer(true)}
	if err := writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		t.Fatal(err)
	}
	state := sessionLifecycle{Binding: binding, Executor: "codex", Workspace: &workspace, State: "idle", CompletedKey: prior.Key, TurnID: "original-turn", PromptHash: workspaceHash(sessionPrompt(dir, prior)), Tools: map[string]bool{}}
	source := providerRecoverySource{Spec: prior, Receipt: Receipt{Session: binding.ID, Workspace: &workspace, Binding: &binding}, Lifecycle: state}
	spec := Spec{Key: "new", Executor: "codex", Persistent: true, SessionID: binding.ID, ResumeFrom: prior.Key, ResumeProvider: completionThread, Prompt: "next"}
	transcript := saveCompletionRecords(t, home, completionRecords(binding, state.TurnID, sessionPrompt(dir, prior)))
	if got, err := s.providerRecovery(context.Background(), spec, source); err != nil || got != workspace {
		t.Fatalf("owned source: %+v %v", got, err)
	}
	other := source
	foreign := binding
	foreign.HostProof = "another-boot-or-node"
	other.Receipt.Binding = &foreign
	other.Lifecycle.Binding = foreign
	if _, err := s.providerRecovery(context.Background(), spec, other); err == nil || err.Error() != "SESSION_RECOVERY_STOP_UNCONFIRMED" {
		t.Fatalf("foreign host proof: %v", err)
	}
	foreign = binding
	foreign.ProviderHomeProof = "another-profile"
	other.Receipt.Binding = &foreign
	other.Lifecycle.Binding = foreign
	if _, err := s.providerRecovery(context.Background(), spec, other); err == nil || err.Error() != "SESSION_RECOVERY_TRANSCRIPT_UNAVAILABLE" {
		t.Fatalf("foreign profile proof: %v", err)
	}
	if err := os.Remove(transcript); err != nil {
		t.Fatal(err)
	}
	if _, err := s.providerRecovery(context.Background(), spec, source); err == nil || err.Error() != "SESSION_RECOVERY_TRANSCRIPT_UNAVAILABLE" {
		t.Fatalf("missing transcript: %v", err)
	}
}
