package agentexecution

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func messageService(t *testing.T) Service {
	t.Helper()
	s := testService(t)
	script := fmt.Sprintf(`#!/bin/sh
root=%s
case "$1" in
 list-sessions) printf '$1\t1792200000\t2026-1018-0900-0001\tmessage-test\n' ;;
 list-panes) printf '2026-1018-0900-0001\t$1\t1792200000\tserver\t%%%%3\t%d\t%%s\n' "$root" ;;
 load-buffer) cat > "$root/received" ;;
 paste-buffer) printf 'paste\n' >> "$root/submits"; test ! -f "$root/fail" ;;
 send-keys|delete-buffer) exit 0 ;;
 *) exit 1 ;;
esac
`, quote(s.Runtime.DataDir), os.Getpid())
	s.Runtime.TmuxBin = filepath.Join(s.Runtime.DataDir, "tmux")
	if e := os.WriteFile(s.Runtime.TmuxBin, []byte(script), 0700); e != nil {
		t.Fatal(e)
	}
	return s
}
func TestMessageDeliveryHasOneSubmissionAndDoesNotClaimExecutionCompletion(t *testing.T) {
	s := messageService(t)
	spec := MessageSpec{Key: "one", SessionID: "message-test", Text: "line one\nline two"}
	r, e := s.SendMessage(spec)
	if e != nil {
		t.Fatal(e)
	}
	if r.State != "delivered" || !r.OutcomeKnown || r.ExecutionTracked || r.SentMS == 0 {
		t.Fatalf("invalid receipt: %+v", r)
	}
	for i := 0; i < 2; i++ {
		again, e := s.SendMessage(spec)
		if e != nil || again != r {
			t.Fatalf("replay=%+v %v", again, e)
		}
	}
	body, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "received"))
	if string(body) != spec.Text {
		t.Fatalf("prompt=%q", body)
	}
	submits, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if strings.Count(string(submits), "paste") != 1 {
		t.Fatalf("duplicate submission: %s", submits)
	}
	spec.Text = "different"
	if _, e = s.SendMessage(spec); e == nil || e.Error() != "MESSAGE_KEY_CONFLICT" {
		t.Fatalf("conflict=%v", e)
	}
}
func TestPartialMessageDeliveryIsUnknownAndNeverReplayed(t *testing.T) {
	s := messageService(t)
	if e := os.WriteFile(filepath.Join(s.Runtime.DataDir, "fail"), nil, 0600); e != nil {
		t.Fatal(e)
	}
	spec := MessageSpec{Key: "partial", SessionID: "message-test", Text: "do work"}
	r, e := s.SendMessage(spec)
	if e != nil || r.State != "unknown" || r.OutcomeKnown {
		t.Fatalf("receipt=%+v error=%v", r, e)
	}
	_ = os.Remove(filepath.Join(s.Runtime.DataDir, "fail"))
	again, e := s.SendMessage(spec)
	if e != nil || again.State != "unknown" {
		t.Fatalf("replayed: %+v %v", again, e)
	}
	submits, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
	if strings.Count(string(submits), "paste") != 1 {
		t.Fatalf("replayed unknown: %s", submits)
	}
}

func TestManagedSessionMessagesRequireTaskContinuationBeforeAnyInput(t *testing.T) {
	for _, field := range []string{"launch", "completed", "initial"} {
		t.Run(field, func(t *testing.T) {
			s := messageService(t)
			binding, err := s.paneBinding("message-test", false)
			if err != nil {
				t.Fatal(err)
			}
			path, err := s.lifecycleFile(binding)
			if err != nil {
				t.Fatal(err)
			}
			state := sessionLifecycle{Binding: binding, State: "idle", Executor: "codex"}
			switch field {
			case "launch":
				state.LaunchKey, state.State = "managed-round", "submitting"
			case "completed":
				state.CompletedKey = "previous-round"
			case "initial":
				state.InitialLaunch = true
			}
			if err = writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			spec := MessageSpec{Key: "blocked", SessionID: "message-test", Text: "Continue original member"}
			for i := 0; i < 2; i++ {
				if _, err = s.SendMessage(spec); err == nil || err.Error() != "TASK_SESSION_BINDING_REQUIRED" {
					t.Fatalf("guard=%v", err)
				}
			}
			dir, _ := s.directory("message:" + spec.Key)
			for _, artifact := range []string{filepath.Join(dir, "message.json"), filepath.Join(s.Runtime.DataDir, "received"), filepath.Join(s.Runtime.DataDir, "submits")} {
				if _, err = os.Stat(artifact); !os.IsNotExist(err) {
					t.Fatalf("unexpected effect %s: %v", artifact, err)
				}
			}
		})
	}
}

func TestRecordedMessageReceiptSurvivesManagedBindingAndMissingSession(t *testing.T) {
	for _, partial := range []bool{false, true} {
		t.Run(fmt.Sprint(partial), func(t *testing.T) {
			s := messageService(t)
			if partial {
				if err := os.WriteFile(filepath.Join(s.Runtime.DataDir, "fail"), nil, 0600); err != nil {
					t.Fatal(err)
				}
			}
			spec := MessageSpec{Key: "historical", SessionID: "message-test", Text: "Original legacy work"}
			receipt, err := s.SendMessage(spec)
			if err != nil {
				t.Fatal(err)
			}
			binding, err := s.paneBinding(spec.SessionID, false)
			if err != nil {
				t.Fatal(err)
			}
			path, err := s.lifecycleFile(binding)
			if err != nil {
				t.Fatal(err)
			}
			if err = writeJSON(path, sessionLifecycle{Binding: binding, State: "busy", LaunchKey: "now-managed"}); err != nil {
				t.Fatal(err)
			}
			if err = os.WriteFile(s.Runtime.TmuxBin, []byte("#!/bin/sh\nexit 1\n"), 0700); err != nil {
				t.Fatal(err)
			}
			again, err := s.SendMessage(spec)
			if err != nil || again != receipt {
				t.Fatalf("receipt=%+v err=%v", again, err)
			}
			submits, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "submits"))
			if strings.Count(string(submits), "paste") != 1 {
				t.Fatalf("replayed receipt: %s", submits)
			}
		})
	}
}
