package agentexecution

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func nativeReconciliationFixture(t *testing.T) (Service, Spec, *Workspace) {
	t.Helper()
	s := testService(t)
	spec := Spec{Key: "abandoned-native", Executor: "native", Directory: t.TempDir(), TimeoutSeconds: 120}
	dir, err := s.directory(spec.Key)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	workspace, err := s.rememberWorkspace(Workspace{Directory: spec.Directory})
	if err != nil {
		t.Fatal(err)
	}
	if err = writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		t.Fatal(err)
	}
	if err = writeJSON(filepath.Join(dir, "receipt.json"), Receipt{State: "native_running", Workspace: &workspace}); err != nil {
		t.Fatal(err)
	}
	return s, spec, &workspace
}

func TestNativeLateStopReleasesOnlyItsOwnWriterAndNeverClaimsSuccess(t *testing.T) {
	s, spec, _ := nativeReconciliationFixture(t)
	release, err := s.claimWorkspace(context.Background(), spec.Directory, spec.Key)
	if err != nil {
		t.Fatal(err)
	}
	proof := NativeStopConfirmation{Stopped: true, EvidenceSHA256: strings.Repeat("a", 64)}
	if _, err = s.ReconcileNative(context.Background(), spec.Key, proof); err == nil || err.Error() != "WORKSPACE_BUSY" {
		t.Fatalf("live holder released: %v", err)
	}
	release()
	ack, err := s.ReconcileNative(context.Background(), spec.Key, proof)
	if err != nil || !ack.Released || !ack.InputStopped || ack.Reused {
		t.Fatalf("late stop: %+v %v", ack, err)
	}
	status, err := s.Status(spec.Key)
	if err != nil || status.Result == nil || status.State != "failed" || status.Result.InputStopped == nil || !*status.Result.InputStopped || status.Result.OutcomeKnown == nil || *status.Result.OutcomeKnown {
		t.Fatalf("stop promoted task outcome: %+v %v", status, err)
	}
	finished := status.Result.FinishedMS
	nextRelease, err := s.claimWorkspace(context.Background(), spec.Directory, "next-native-writer")
	if err != nil {
		t.Fatal(err)
	}
	defer nextRelease()
	ack, err = s.ReconcileNative(context.Background(), spec.Key, proof)
	if err != nil || !ack.Reused {
		t.Fatalf("replay changed the next writer: %+v %v", ack, err)
	}
	status, err = s.Status(spec.Key)
	if err != nil || status.Result.FinishedMS != finished {
		t.Fatal("replay rewrote durable evidence")
	}
}

func TestNativeReconciliationRejectsMissingOrChangedBindings(t *testing.T) {
	for _, scenario := range []string{"invalid-proof", "not-stopped", "coding-executor", "writer-changed", "preparing"} {
		t.Run(scenario, func(t *testing.T) {
			s, spec, workspace := nativeReconciliationFixture(t)
			release, err := s.claimWorkspace(context.Background(), spec.Directory, spec.Key)
			if err != nil {
				t.Fatal(err)
			}
			release()
			dir, _ := s.directory(spec.Key)
			proof := NativeStopConfirmation{Stopped: true, EvidenceSHA256: strings.Repeat("b", 64)}
			switch scenario {
			case "invalid-proof":
				proof.EvidenceSHA256 = "not-a-digest"
			case "not-stopped":
				proof.Stopped = false
			case "coding-executor":
				spec.Executor = "codex"
				if err = writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
					t.Fatal(err)
				}
			case "preparing":
				if err = writeJSON(filepath.Join(dir, "receipt.json"), Receipt{State: "preparing", Workspace: workspace}); err != nil {
					t.Fatal(err)
				}
			case "writer-changed":
				root, unlock, err := s.lockWorkspaceWriter(context.Background(), spec.Directory)
				if err != nil {
					t.Fatal(err)
				}
				err = writeJSON(filepath.Join(root, "writer.json"), map[string]string{"key": "different-writer"})
				unlock()
				if err != nil {
					t.Fatal(err)
				}
			}
			if _, err = s.ReconcileNative(context.Background(), spec.Key, proof); err == nil {
				t.Fatal("invalid stop evidence cleared a fence")
			}
			if _, err = os.Stat(filepath.Join(dir, "result.json")); !os.IsNotExist(err) {
				t.Fatal("invalid evidence published a result")
			}
		})
	}
}

func TestNativeReconciliationDoesNotWaitForLivePreparation(t *testing.T) {
	s, spec, _ := nativeReconciliationFixture(t)
	dir, _ := s.directory(spec.Key)
	release, err := lock(filepath.Join(dir, "launch.lock"))
	if err != nil {
		t.Fatal(err)
	}
	defer release()
	if _, err := s.ReconcileNative(context.Background(), spec.Key, NativeStopConfirmation{Stopped: true, EvidenceSHA256: strings.Repeat("c", 64)}); err == nil || err.Error() != "NATIVE_RECONCILIATION_BUSY" {
		t.Fatalf("live preparation was reconciled: %v", err)
	}
}

func TestNativeReconciliationThroughRealCLI(t *testing.T) {
	s, spec, _ := nativeReconciliationFixture(t)
	release, err := s.claimWorkspace(context.Background(), spec.Directory, spec.Key)
	if err != nil {
		t.Fatal(err)
	}
	release()
	root, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(t.TempDir(), "roami")
	build := exec.Command("go", "build", "-o", binary, "./cmd/roami")
	build.Dir = root
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, output)
	}
	proof := NativeStopConfirmation{Stopped: true, EvidenceSHA256: strings.Repeat("d", 64)}
	content, _ := json.Marshal(proof)
	command := exec.Command(binary, "agent", "execution", "reconcile-native", "--key", spec.Key, "--file", "-")
	command.Env = append(os.Environ(), "ROAMI_HOME="+s.Runtime.HomeDir, "ROAMI_DATA="+s.Runtime.DataDir, "ROAMI_DATABASE_DIR="+filepath.Join(s.Runtime.DataDir, "database"), "ROAMI_BACKUP_DIR="+filepath.Join(s.Runtime.DataDir, "backups"), "ROAMI_CONFIG="+filepath.Join(s.Runtime.HomeDir, "config.yaml"))
	command.Stdin = strings.NewReader(string(content))
	output, err := command.CombinedOutput()
	var ack NativeReconciliation
	if err != nil || json.Unmarshal(output, &ack) != nil || !ack.Released || ack.LaunchKey != spec.Key || ack.EvidenceSHA256 != proof.EvidenceSHA256 {
		t.Fatalf("CLI reconciliation: %v %s", err, output)
	}
	next, err := s.claimWorkspace(context.Background(), spec.Directory, "after-cli-reconciliation")
	if err != nil {
		t.Fatal(err)
	}
	next()
}

func TestNativeReconciliationThroughRealPythonAndCLI(t *testing.T) {
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv required")
	}
	s := testService(t)
	repository, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	recordRuntimeSources(t, repository, "native_reconciliation_scenario.py")
	if _, err := os.ReadFile(filepath.Join(repository, "agent-runtime", "tests", "test_native_reconciliation.py")); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(t.TempDir(), "roami")
	build := exec.Command("go", "build", "-o", binary, "./cmd/roami")
	build.Dir = repository
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, output)
	}
	directory := t.TempDir()
	command := exec.Command("uv", "run", "--frozen", "--directory", filepath.Join(repository, "agent-runtime"), "python", "tests/native_reconciliation_scenario.py", binary, s.Runtime.DataDir, directory)
	command.Env = append(os.Environ(), "ROAMI_HOME="+s.Runtime.HomeDir, "ROAMI_DATA="+s.Runtime.DataDir, "ROAMI_DATABASE_DIR="+filepath.Join(s.Runtime.DataDir, "database"), "ROAMI_BACKUP_DIR="+filepath.Join(s.Runtime.DataDir, "backups"), "ROAMI_CONFIG="+filepath.Join(s.Runtime.HomeDir, "config.yaml"))
	output, err := command.CombinedOutput()
	if err != nil || !strings.Contains(string(output), "native reconciliation scenario passed") {
		t.Fatalf("cross-language reconciliation: %v\n%s", err, output)
	}
	release, err := s.claimWorkspace(context.Background(), directory, "after-python-reconciliation")
	if err != nil {
		t.Fatal(err)
	}
	release()
}
