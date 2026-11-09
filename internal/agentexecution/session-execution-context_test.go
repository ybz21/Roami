package agentexecution

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestNativeContextObservesOriginalRunWithoutWritingOrGrantingPermission(t *testing.T) {
	s, binding := sessionFixture(t)
	seedSession(t, s, binding)
	spec, prompt := startSessionTask(t, s, binding, "native-context")
	statePath, err := s.lifecycleFile(binding)
	if err != nil {
		t.Fatal(err)
	}
	dir, _ := s.directory(spec.Key)
	before := map[string][]byte{}
	for _, path := range []string{statePath, filepath.Join(dir, "spec.json"), filepath.Join(dir, "receipt.json")} {
		before[path], err = os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
	}
	observed, err := s.CurrentNativeContext(binding.Pane, os.Getpid())
	if err != nil {
		t.Fatal(err)
	}
	if observed.SessionID != binding.ID || observed.Executor != "codex" || observed.ProviderConversationID != "provider-thread" || observed.ProviderTurnID != "task-turn" || observed.LaunchKey != spec.Key || observed.WorkspaceID == "" || len(observed.ObservationSHA256) != 64 || !observed.ObservationOnly || observed.PublicationAuthorized {
		t.Fatalf("wrong original context: %+v", observed)
	}
	encoded, _ := json.Marshal(observed)
	if bytes.Contains(encoded, []byte("Follow up")) {
		t.Fatal("private task instructions leaked")
	}
	for path, expected := range before {
		actual, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(expected, actual) {
			t.Fatalf("observation changed %s", filepath.Base(path))
		}
	}
	if _, err = s.CurrentNativeContext(binding.Pane, os.Getppid()); err == nil {
		t.Fatal("an ancestor outside this pane acquired its context")
	}
	if _, err = s.CurrentNativeContext("%other", os.Getpid()); err == nil {
		t.Fatal("a different pane hint was accepted")
	}
	if err = s.applySessionEvent("codex", binding, SessionEvent{Type: "agent-turn-complete", ThreadID: "provider-thread", NotificationTurn: "task-turn", Inputs: []string{prompt}, LastAssistant: "done"}); err != nil {
		t.Fatal(err)
	}
	if _, err = s.CurrentNativeContext(binding.Pane, os.Getpid()); err == nil {
		t.Fatal("completed launch still appeared current")
	}
}

func TestNativeContextRejectsConflictingLifecycleAndExecutionRecords(t *testing.T) {
	for _, change := range []string{"provider", "launch", "receipt", "receipt-ended", "ended", "ended-idle", "unknown", "prompt"} {
		t.Run(change, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedSession(t, s, binding)
			spec, _ := startSessionTask(t, s, binding, "context-conflict")
			path, _ := s.lifecycleFile(binding)
			dir, _ := s.directory(spec.Key)
			var state sessionLifecycle
			if err := readJSON(path, &state); err != nil {
				t.Fatal(err)
			}
			switch change {
			case "provider":
				state.Binding.ProviderID = "other-provider"
			case "launch":
				state.LaunchKey = "other-launch"
			case "ended-idle":
				state.EndedIdle = true
			case "unknown":
				state.State = "unknown"
			case "prompt":
				state.PromptHash = "different-input"
			case "receipt", "receipt-ended":
				var receipt Receipt
				if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
					t.Fatal(err)
				}
				if change == "receipt" {
					receipt.Binding.ProviderID = "other-provider"
				} else {
					receipt.State = "succeeded"
				}
				if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
					t.Fatal(err)
				}
			case "ended":
				if err := writeJSON(filepath.Join(dir, "result.json"), Result{State: "succeeded"}); err != nil {
					t.Fatal(err)
				}
			}
			if err := writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			if _, err := s.CurrentNativeContext(binding.Pane, os.Getpid()); err == nil {
				t.Fatal("conflicting context was accepted")
			}
		})
	}
}

func TestNativeContextRetainsClaudeProviderAndCurrentPrompt(t *testing.T) {
	s, binding := sessionFixture(t)
	seedClaudeSession(t, s, binding)
	spec := startClaudeTask(t, s, binding, "claude-native-context")
	observed, err := s.CurrentNativeContext(binding.Pane, os.Getpid())
	if err != nil {
		t.Fatal(err)
	}
	if observed.Executor != "claude" || observed.SessionID != binding.ID || observed.ProviderConversationID != "provider-thread" || observed.ProviderTurnID != "task-prompt" || observed.LaunchKey != spec.Key || !observed.ObservationOnly || observed.PublicationAuthorized {
		t.Fatalf("Claude context drifted or granted authority: %+v", observed)
	}
}

func TestNativeCallerRequiresLiveSameSessionAncestry(t *testing.T) {
	binding := SessionBinding{PID: 10, Processes: map[int]string{10: "root"}}
	snapshot := map[int]paneProcess{10: {Parent: 1, Token: "root"}, 20: {Parent: 10, Token: "child"}, 30: {Parent: 20, Token: "caller"}, 40: {Parent: 1, Token: "sibling"}}
	if token, err := nativeCallerToken(snapshot, binding, 30); err != nil || token != "caller" {
		t.Fatalf("current descendant rejected: %q %v", token, err)
	}
	for _, change := range []string{"sibling", "foreign", "recycled", "cycle", "missing"} {
		t.Run(change, func(t *testing.T) {
			copy := map[int]paneProcess{}
			for k, v := range snapshot {
				copy[k] = v
			}
			current, caller := binding, 30
			switch change {
			case "sibling":
				caller = 40
			case "foreign":
				current.ForeignProcesses = map[int]string{20: "child"}
			case "recycled":
				copy[10] = paneProcess{Parent: 1, Token: "reused"}
			case "cycle":
				copy[20] = paneProcess{Parent: 30, Token: "child"}
			case "missing":
				delete(copy, 20)
			}
			if _, err := nativeCallerToken(copy, current, caller); err == nil {
				t.Fatal("untrusted ancestry accepted")
			}
		})
	}
}
