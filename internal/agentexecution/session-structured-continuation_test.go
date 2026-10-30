package agentexecution

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStructuredFollowupsRetainContextAfterSuccessFailureAndCancellation(t *testing.T) {
	for _, provider := range []string{"opencode", "pi"} {
		t.Run(provider, func(t *testing.T) {
			s, binding := sessionFixture(t)
			snapshot, scope, scoped, err := paneProcessSnapshot(binding.PID)
			if err != nil {
				t.Fatal(err)
			}
			binding.ProviderID, binding.Scope, binding.Processes = "fixture-session", scope, scoped
			binding.ForeignProcesses = map[int]string{}
			descendants := descendantProcesses(snapshot, binding.PID)
			for pid, token := range scoped {
				if descendants[pid] == "" {
					binding.ForeignProcesses[pid] = token
				}
			}
			path, err := s.lifecycleFile(binding)
			if err != nil {
				t.Fatal(err)
			}
			state := sessionLifecycle{Structured: true, Model: "fixture/model", Permission: "auto", Binding: binding, Executor: provider, State: "busy", Tools: map[string]bool{}}
			if err = writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			bin := filepath.Join(t.TempDir(), provider)
			script := `#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
args = sys.argv[1:]
kind = Path(sys.argv[0]).name
if kind == "opencode" and args[:2] == ["session", "export"]:
    print(Path("export.json").read_text())
    sys.exit(0)
flag = "--session" if kind == "opencode" else "--session-id"
assert args[args.index(flag) + 1] == "fixture-session", args
assert args[args.index("--model") + 1] == "fixture/model", args
if kind == "opencode":
    assert "--auto" in args, args
prompt = sys.stdin.read() if kind == "opencode" else args[-1]
with Path("executed.jsonl").open("a") as log:
    log.write(json.dumps({"prompt": prompt, "provider": "fixture-session"}) + "\n")
text = "Reply to " + prompt
failed = prompt == "failure"
stamp = int(time.time() * 1000)
if kind == "opencode":
    Path("export.json").write_text(json.dumps({
        "info": {"id": "fixture-session", "outcome": "succeeded", "location": {"directory": os.getcwd()}},
        "messages": [
            {"type": "user", "text": prompt, "time": {"created": stamp}},
            {"type": "assistant", "finish": "stop", "time": {"completed": stamp}, "content": [{"type": "text", "text": text}]},
            {"type": "idle", "outcome": "succeeded"}]}))
    print(json.dumps({"type": "text", "sessionID": "fixture-session", "part": {"text": text}}))
else:
    print(json.dumps({"type": "session", "id": "fixture-session"}))
    print(json.dumps({"type": "message_end", "message": {"role": "assistant", "stopReason": "error" if failed else "stop", "content": [{"type": "text", "text": text}]}}))
    print(json.dumps({"type": "agent_settled", "aborted": False}))
sys.exit(7 if failed else 0)
`
			if err = os.WriteFile(bin, []byte(script), 0700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", filepath.Dir(bin)+string(os.PathListSeparator)+os.Getenv("PATH"))
			busy := Spec{Key: "busy", Executor: provider, SessionID: binding.ID, Prompt: "must wait"}
			for _, waiting := range []string{"busy", "unknown"} {
				state.State = waiting
				if err = writeJSON(path, state); err != nil {
					t.Fatal(err)
				}
				if _, err = s.Launch(context.Background(), busy); err == nil || err.Error() != "SESSION_NOT_IDLE" {
					t.Fatalf("%s admitted input: %v", waiting, err)
				}
				dir, _ := s.directory(busy.Key)
				if _, err = os.Stat(filepath.Join(dir, "spec.json")); !os.IsNotExist(err) {
					t.Fatal("rejected input was journaled as a submission")
				}
			}
			state.State = "idle"
			if err = writeJSON(path, state); err != nil {
				t.Fatal(err)
			}
			for _, phase := range []string{"success", "failure", "cancelled", "resumed"} {
				spec := Spec{Key: phase, Executor: provider, SessionID: binding.ID, Prompt: phase}
				if _, err = s.Launch(context.Background(), spec); err != nil {
					t.Fatal(err)
				}
				if _, err = s.Launch(context.Background(), spec); err != nil {
					t.Fatal(err)
				}
				if phase == "cancelled" {
					if _, err = s.Cancel(spec.Key); err != nil {
						t.Fatal(err)
					}
				}
				if err = s.structuredTurn(context.Background(), path, spec.Key, false, io.Discard, io.Discard); err != nil {
					t.Fatal(err)
				}
				status, err := s.Status(spec.Key)
				want := "succeeded"
				if phase == "failure" {
					want = "failed"
				} else if phase == "cancelled" {
					want = "cancelled"
				}
				if err != nil || status.State != want || status.Result == nil || status.Binding == nil || status.Binding.ProviderID != binding.ProviderID || status.Session != binding.ID {
					t.Fatalf("%s lost result or original context: %+v %v", phase, status, err)
				}
				if status.Result.InputStopped == nil || !*status.Result.InputStopped {
					t.Fatal("completion omitted stop proof")
				}
				if _, err = s.Launch(context.Background(), spec); err != nil {
					t.Fatal(err)
				}
			}
			calls, err := os.ReadFile(filepath.Join(binding.Directory, "executed.jsonl"))
			if err != nil || strings.Count(string(calls), "\n") != 3 || strings.Contains(string(calls), `"prompt": "cancelled"`) {
				t.Fatalf("input replayed or cancelled input ran: %s %v", calls, err)
			}
		})
	}
}
