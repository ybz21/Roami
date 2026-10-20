package agentexecution

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func testService(t *testing.T) Service {
	t.Helper()
	root := t.TempDir()
	return Service{Runtime: runtime.Runtime{HomeDir: root, DataDir: root, Now: time.Now}}
}

func TestUnknownLaunchNeverExecutesAgain(t *testing.T) {
	s := testService(t)
	dir, _ := s.directory("lost-receipt")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	spec := Spec{Key: "lost-receipt", Executor: "codex", Directory: dir, Prompt: "write", TimeoutSeconds: 10}
	if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "started"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	err := s.Run(context.Background(), spec.Key, io.Discard, io.Discard)
	if err == nil || !strings.Contains(err.Error(), "EXECUTION_ALREADY_STARTED") {
		t.Fatalf("must not replay an unknown execution: %v", err)
	}
}

func TestMissingLaunchAndPartiallyWrittenLaunchAreDifferent(t *testing.T) {
	s := testService(t)
	status, err := s.Status("missing")
	if err != nil || status.State != "not_started" {
		t.Fatalf("missing launch: %+v, %v", status, err)
	}
	dir, _ := s.directory("partial")
	if err = os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err = writeJSON(filepath.Join(dir, "spec.json"), Spec{Key: "partial"}); err != nil {
		t.Fatal(err)
	}
	status, err = s.Status("partial")
	if err != nil || status.State != "unknown" {
		t.Fatalf("partial launch must not be replayed: %+v, %v", status, err)
	}
}

func TestObservationFailureDoesNotClaimAgentStopped(t *testing.T) {
	s := testService(t)
	dir, _ := s.directory("observation")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), Receipt{State: "launched", Session: "known"}); err != nil {
		t.Fatal(err)
	}
	tmux := filepath.Join(dir, "tmux")
	if err := os.WriteFile(tmux, []byte("#!/bin/sh\necho 'permission denied' >&2\nexit 1\n"), 0700); err != nil {
		t.Fatal(err)
	}
	s.Runtime.TmuxBin = tmux
	_, err := s.Status("observation")
	if err == nil || !strings.Contains(err.Error(), "EXECUTION_OBSERVATION_FAILED") {
		t.Fatalf("must preserve observation uncertainty: %v", err)
	}
	if _, err = s.Cancel("observation"); err == nil {
		t.Fatal("cannot confirm cancellation without observing runner")
	}
	if _, err = os.Stat(filepath.Join(dir, "cancel.json")); !os.IsNotExist(err) {
		t.Fatal("uncertain cancellation mutated execution")
	}
}

func TestStatusKeepsDurableCancellationWhenTmuxExitsDuringObservation(t *testing.T) {
	s := testService(t)
	dir, _ := s.directory("cancel-race")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), Receipt{State: "launched", Session: "finishing"}); err != nil {
		t.Fatal(err)
	}
	tmux := filepath.Join(dir, "tmux")
	script := "#!/bin/sh\nprintf '%s' " + quote(`{"state":"cancelled","summary":"","exitCode":-1,"finishedMs":1}`) + " > " + quote(filepath.Join(dir, "result.json")) + "\nexit 1\n"
	if err := os.WriteFile(tmux, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	s.Runtime.TmuxBin = tmux
	status, err := s.Status("cancel-race")
	if err != nil || status.State != "cancelled" || status.Result == nil || status.Result.State != "cancelled" {
		t.Fatalf("durable cancellation lost during tmux shutdown: %+v, %v", status, err)
	}
}

func TestRunnerBoundsOutputAndKeepsNonzeroExit(t *testing.T) {
	s := testService(t)
	dir, _ := s.directory("bounded")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(dir, "codex")
	t.Setenv("GIT_DIR", "/foreign/repository")
	t.Setenv("GIT_INDEX_FILE", "/foreign/index")
	t.Setenv("GIT_IMPLICIT_WORK_TREE", "0")
	script := "#!/bin/sh\nif [ -n \"${GIT_DIR+x}${GIT_INDEX_FILE+x}${GIT_IMPLICIT_WORK_TREE+x}\" ]; then exit 77; fi\nhead -c 100000 /dev/zero | tr '\\000' 'x'\nprintf 'diagnostic' >&2\nexit 7\n"
	if err := os.WriteFile(bin, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	spec := Spec{Key: "bounded", Executor: "codex", Directory: dir, Prompt: "test", TimeoutSeconds: 10}
	if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), Receipt{State: "launched"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Run(context.Background(), spec.Key, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	status, err := s.Status(spec.Key)
	if err != nil {
		t.Fatal(err)
	}
	if status.Result == nil || status.State != "failed" || status.Result.ExitCode != 7 || len(status.Result.Summary) != 32000 || status.Result.Stderr != "diagnostic" {
		t.Fatalf("unexpected result: %+v", status)
	}
	// A completed execution is replayable even after the coding binary disappears.
	if err = os.Remove(bin); err != nil {
		t.Fatal(err)
	}
	replay, err := s.Launch(context.Background(), spec)
	if err != nil || replay.Result == nil || replay.Result.ExitCode != 7 {
		t.Fatalf("completed launch was not replayed: %+v, %v", replay, err)
	}
	if err = s.Run(context.Background(), spec.Key, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
}

func TestDeadlineRetainsPartialOutputForInspection(t *testing.T) {
	s := testService(t)
	dir, _ := s.directory("deadline-evidence")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(dir, "codex")
	if err := os.WriteFile(bin, []byte("#!/bin/sh\nprintf 'partial deliverable evidence'\nprintf 'diagnostic' >&2\nsleep 5\n"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
	spec := Spec{Key: "deadline-evidence", Executor: "codex", Directory: dir, Prompt: "work", TimeoutSeconds: 1}
	if err := writeJSON(filepath.Join(dir, "spec.json"), spec); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), Receipt{State: "running"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Run(context.Background(), spec.Key, io.Discard, io.Discard); err != nil {
		t.Fatal(err)
	}
	status, err := s.Status(spec.Key)
	if err != nil {
		t.Fatal(err)
	}
	if status.Result == nil || status.Result.State != "failed" || status.Result.Summary != "EXECUTION_DEADLINE_OR_INTERRUPTION" || status.Result.Output != "partial deliverable evidence" || status.Result.Stderr != "diagnostic" {
		t.Fatalf("lost deadline evidence: %+v", status.Result)
	}
}

func TestUnlimitedExecutionContextRemainsCancellable(t *testing.T) {
	if executionDeadline(0) != 0 {
		t.Fatal("zero must not become an immediate deadline")
	}
	parent, stop := context.WithCancel(context.Background())
	ctx, cancel := executionContext(parent, 0)
	defer cancel()
	if _, ok := ctx.Deadline(); ok {
		t.Fatal("unexpected task-wide deadline")
	}
	stop()
	<-ctx.Done()
	if ctx.Err() != context.Canceled {
		t.Fatal(ctx.Err())
	}
}

func TestExecutionTimeoutIsOptionalAndCanExceedOneDay(t *testing.T) {
	if executionDeadline(0) != 0 || !validExecutionTimeout(0) || validExecutionTimeout(-1) {
		t.Fatal("invalid optional execution timeout")
	}
	seconds := 3 * 24 * 60 * 60
	if !validExecutionTimeout(seconds) {
		t.Fatal("a three-day task is a valid explicit deadline")
	}
	deadline := executionDeadline(seconds)
	if deadline <= time.Now().Add(71*time.Hour).UnixMilli() {
		t.Fatal("explicit deadline was truncated")
	}
	ctx, cancel := executionContext(context.Background(), 0)
	defer cancel()
	if _, bounded := ctx.Deadline(); bounded {
		t.Fatal("default execution has no deadline")
	}
}
