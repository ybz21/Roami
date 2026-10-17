package agentexecution

import (
	"context"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/memguard"
)

func sessionFixture(t *testing.T) (Service, SessionBinding) {
	t.Helper()
	if _, err := os.Stat("/proc/self/stat"); err != nil {
		t.Skip("process proof requires procfs")
	}
	if _, _, err := memguard.ScopeProcesses(os.Getpid()); err != nil {
		t.Skip("completion proof requires a dedicated tmux pane scope")
	}
	s := testService(t)
	directory := t.TempDir()
	binding := SessionBinding{Name: "2026-1017-0900-0001", ID: "2026-1017-0900-0001", TmuxID: "$1", Created: "1792200000", Server: "fixture-server", Pane: "%3", PID: os.Getpid(), Directory: directory}
	identity := fmt.Sprintf("%s\t%s\t%s\t%s\t%s\t%d\t%s\n", binding.Name, binding.TmuxID, binding.Created, binding.Server, binding.Pane, binding.PID, binding.Directory)
	if err := os.WriteFile(filepath.Join(s.Runtime.DataDir, "identity"), []byte(identity), 0600); err != nil {
		t.Fatal(err)
	}
	bin := filepath.Join(s.Runtime.DataDir, "tmux")
	script := `#!/bin/sh
root=` + quote(s.Runtime.DataDir) + `
case "$1" in
 list-sessions) printf '$1\t1792200000\t2026-1017-0900-0001\tlabel\n' ;;
 list-panes|display-message) cat "$root/identity" ;;
 load-buffer) cat > "$root/prompt" ;;
 paste-buffer) printf 'submitted\n' >> "$root/submits"; test ! -f "$root/fail-submit" ;;
 send-keys|delete-buffer) exit 0 ;;
 *) exit 1 ;;
esac
`
	if err := os.WriteFile(bin, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	s.Runtime.TmuxBin = bin
	return s, binding
}

func seedSession(t *testing.T, s Service, binding SessionBinding) {
	t.Helper()
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: "provider-thread", TurnID: "seed-turn", Prompt: "manual question"}); err != nil {
		t.Fatal(err)
	}
	if err := s.applySessionEvent("codex", binding, SessionEvent{Type: "agent-turn-complete", ThreadID: "provider-thread", NotificationTurn: "seed-turn", Inputs: []string{"manual question"}, LastAssistant: "Ready"}); err != nil {
		t.Fatal(err)
	}
}

func startSessionTask(t *testing.T, s Service, binding SessionBinding, key string) (Spec, string) {
	t.Helper()
	spec := Spec{Key: key, Executor: "codex", SessionID: binding.ID, Prompt: "Follow up\nwith evidence", TimeoutSeconds: 30}
	status, err := s.Launch(context.Background(), spec)
	if err != nil || status.Binding == nil || status.Binding.ProviderID != "provider-thread" {
		t.Fatalf("continuation: %+v %v", status, err)
	}
	prompt, err := os.ReadFile(filepath.Join(s.Runtime.DataDir, "prompt"))
	if err != nil {
		t.Fatal(err)
	}
	if err = s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: "provider-thread", TurnID: "task-turn", Prompt: string(prompt)}); err != nil {
		t.Fatal(err)
	}
	status, err = s.Status(key)
	if err != nil || status.State != "running" {
		t.Fatalf("start receipt: %+v %v", status, err)
	}
	return spec, string(prompt)
}

func TestSessionContinuationUsesOneDurableSubmissionAndOriginalIdentity(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	spec, prompt := startSessionTask(t, s, binding, "continuation")
	if _, err := s.Launch(context.Background(), spec); err != nil {
		t.Fatal(err)
	}
	submits, err := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if err != nil || strings.Count(string(submits), "submitted") != 1 {
		t.Fatalf("replayed task: %s %v", submits, err)
	}
	changed := spec
	changed.Prompt = "different task"
	if _, err := s.Launch(context.Background(), changed); err == nil || err.Error() != "LAUNCH_KEY_CONFLICT" {
		t.Fatalf("conflicting key: %v", err)
	}
	if _, err := s.claimWorkspace(context.Background(), binding.Directory, "overlap"); err == nil || err.Error() != "WORKSPACE_OUTCOME_UNKNOWN" {
		t.Fatalf("writer was not fenced: %v", err)
	}
	// Stop is only a hook opportunity: another hook may still continue the turn.
	if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "Stop", ProviderID: "provider-thread", TurnID: "task-turn"}); err != nil {
		t.Fatal(err)
	}
	status, err := s.Status(spec.Key)
	if err != nil || status.Result != nil {
		t.Fatalf("Stop claimed completion: %+v %v", status, err)
	}
	completion := SessionEvent{Type: "agent-turn-complete", ThreadID: "provider-thread", NotificationTurn: "task-turn", Inputs: []string{prompt}, LastAssistant: "Checked result"}
	if err = s.applySessionEvent("codex", binding, completion); err != nil {
		t.Fatal(err)
	}
	status, err = s.Status(spec.Key)
	if err != nil || status.Result == nil || status.Result.Summary != "Checked result" || status.State != "succeeded" {
		t.Fatalf("completion: %+v %v", status, err)
	}
	if err = s.applySessionEvent("codex", binding, completion); err != nil {
		t.Fatal(err)
	}
	again, err := s.Status(spec.Key)
	if err != nil || again.Result.FinishedMS != status.Result.FinishedMS {
		t.Fatalf("duplicate changed result: %+v %v", again, err)
	}
	release, err := s.claimWorkspace(context.Background(), binding.Directory, "next-writer")
	if err != nil {
		t.Fatal(err)
	}
	release()
}

func TestSessionSubmissionFailureNeverResendsOrClaimsNotStarted(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	if err := os.WriteFile(filepath.Join(s.Runtime.DataDir, "fail-submit"), nil, 0600); err != nil {
		t.Fatal(err)
	}
	spec := Spec{Key: "uncertain", Executor: "codex", SessionID: binding.ID, Prompt: "work", TimeoutSeconds: 30}
	if _, err := s.Launch(context.Background(), spec); err == nil || err.Error() != "SESSION_SUBMISSION_UNKNOWN" {
		t.Fatalf("submission uncertainty: %v", err)
	}
	status, err := s.Launch(context.Background(), spec)
	if err != nil || status.State != "unknown" {
		t.Fatalf("recovery: %+v %v", status, err)
	}
	submits, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if strings.Count(string(submits), "submitted") != 1 {
		t.Fatalf("uncertain submission replayed: %s", submits)
	}
	if status, err = s.Cancel(spec.Key); err != nil || status.State != "unknown" || status.Result != nil {
		t.Fatalf("cancel request falsely confirmed an unobserved turn: %+v %v", status, err)
	}
}

func TestSessionCompletionQuarantinesMismatchesAndLiveChildren(t *testing.T) {
	for _, mode := range []string{"wrong-turn", "wrong-input", "wrong-provider", "unfinished-tool", "new-input", "background-process", "orphan-process"} {
		t.Run(mode, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedSession(t, s, binding)
			spec, prompt := startSessionTask(t, s, binding, mode)
			completion := SessionEvent{Type: "agent-turn-complete", ThreadID: "provider-thread", NotificationTurn: "task-turn", Inputs: []string{prompt}, LastAssistant: "Claimed complete"}
			switch mode {
			case "wrong-turn":
				completion.NotificationTurn = "other"
			case "wrong-input":
				completion.Inputs = []string{"other input"}
			case "wrong-provider":
				completion.ThreadID = "other-provider"
			case "unfinished-tool":
				if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "PreToolUse", ProviderID: "provider-thread", TurnID: "task-turn", ToolID: "live-tool"}); err != nil {
					t.Fatal(err)
				}
			case "new-input":
				if err := s.applySessionEvent("codex", binding, SessionEvent{Hook: "UserPromptSubmit", ProviderID: "provider-thread", TurnID: "manual-turn", Prompt: "manual override"}); err != nil {
					t.Fatal(err)
				}
			case "background-process":
				child := exec.Command("sleep", "30")
				if err := child.Start(); err != nil {
					t.Fatal(err)
				}
				defer func() { _ = child.Process.Kill(); _ = child.Wait() }()
			case "orphan-process":
				pidFile := filepath.Join(t.TempDir(), "orphan")
				command := exec.Command("sh", "-c", "sleep 30 >/dev/null 2>&1 & echo $! > "+quote(pidFile))
				if err := command.Run(); err != nil {
					t.Fatal(err)
				}
				data, err := os.ReadFile(pidFile)
				if err != nil {
					t.Fatal(err)
				}
				pid, err := strconv.Atoi(strings.TrimSpace(string(data)))
				if err != nil {
					t.Fatal(err)
				}
				defer func() {
					process, _ := os.FindProcess(pid)
					if process != nil {
						_ = process.Kill()
					}
				}()
			}
			if err := s.applySessionEvent("codex", binding, completion); err != nil {
				t.Fatal(err)
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.State != "unknown" || status.Result != nil {
				t.Fatalf("false completion: %+v %v", status, err)
			}
			if _, err = s.claimWorkspace(context.Background(), binding.Directory, "unsafe-reuse"); err == nil {
				t.Fatal("unknown work released the writer")
			}
		})
	}
}

func TestSessionCancellationDeniesNewToolsAndWaitsForCompletion(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	spec, prompt := startSessionTask(t, s, binding, "cancel")
	status, err := s.Cancel(spec.Key)
	if err != nil || status.State != "cancelling" || status.Result != nil {
		t.Fatalf("cancel request: %+v %v", status, err)
	}
	err = s.applySessionEvent("codex", binding, SessionEvent{Hook: "PreToolUse", ProviderID: "provider-thread", TurnID: "task-turn", ToolID: "must-not-start"})
	if err == nil || err.Error() != "SESSION_TASK_CANCEL_REQUESTED" {
		t.Fatalf("new tool not denied: %v", err)
	}
	if err = s.applySessionEvent("codex", binding, SessionEvent{Type: "agent-turn-complete", ThreadID: "provider-thread", NotificationTurn: "task-turn", Inputs: []string{prompt}}); err != nil {
		t.Fatal(err)
	}
	status, err = s.Status(spec.Key)
	if err != nil || status.State != "cancelled" || status.Result == nil {
		t.Fatalf("cancel completion: %+v %v", status, err)
	}
}

func TestUnenrolledSessionIsRejectedBeforeSubmitting(t *testing.T) {
	s, binding := sessionFixture(t)
	_, err := s.Launch(context.Background(), Spec{Key: "unready", Executor: "codex", SessionID: binding.ID, Prompt: "work", TimeoutSeconds: 30})
	if err == nil || err.Error() != "SESSION_LIFECYCLE_UNAVAILABLE" {
		t.Fatalf("unready session: %v", err)
	}
	if _, err := os.Stat(filepath.Join(s.Runtime.DataDir, "submits")); !os.IsNotExist(err) {
		t.Fatal("unready session received a prompt")
	}
}

func TestSessionContinuationThroughRealPythonAndGoCLI(t *testing.T) {
	if _, err := exec.LookPath("uv"); err != nil {
		t.Skip("uv required")
	}
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	repository, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	if err = filepath.WalkDir(filepath.Join(repository, "agent-runtime", "src"), func(path string, entry fs.DirEntry, problem error) error {
		if problem != nil {
			return problem
		}
		if !entry.IsDir() && strings.HasSuffix(path, ".py") {
			_, problem = os.ReadFile(path)
		}
		return problem
	}); err != nil {
		t.Fatal(err)
	}
	if _, err = os.ReadFile(filepath.Join(repository, "agent-runtime", "tests", "session_continuation_scenario.py")); err != nil {
		t.Fatal(err)
	}
	binary := filepath.Join(t.TempDir(), "roami")
	build := exec.Command("go", "build", "-o", binary, "./cmd/roami")
	build.Dir = repository
	if output, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build: %v %s", err, output)
	}
	command := exec.Command("uv", "run", "--frozen", "--directory", filepath.Join(repository, "agent-runtime"), "python", "tests/session_continuation_scenario.py", binary, s.Runtime.DataDir, binding.ID)
	command.Env = append(os.Environ(), "ROAMI_HOME="+s.Runtime.HomeDir, "ROAMI_DATA="+s.Runtime.DataDir, "TMUX_BIN="+s.Runtime.TmuxBin)
	output, err := command.CombinedOutput()
	if err != nil || !strings.Contains(string(output), "session continuation scenario passed") {
		t.Fatalf("continuation integration: %v\n%s", err, output)
	}
}
