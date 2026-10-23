package agentexecution

import (
	"context"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStructuredCompletionRequiresNativeProof(t *testing.T) {
	cases := []struct {
		name, kind, stream string
		success            bool
	}{
		{"open final", "opencode", `{"type":"text","sessionID":"ses_1","part":{"text":"done"}}
{"type":"step_finish","sessionID":"ses_1","part":{"reason":"stop"}}`, true},
		{"open tools still running", "opencode", `{"type":"text","sessionID":"ses_1","part":{"text":"done"}}
{"type":"step_finish","sessionID":"ses_1","part":{"reason":"tool-calls"}}`, false},
		{"open error then stop", "opencode", `{"type":"error","sessionID":"ses_1"}
{"type":"text","sessionID":"ses_1","part":{"text":"done"}}
{"type":"step_finish","sessionID":"ses_1","part":{"reason":"stop"}}`, false},
		{"mixed session", "opencode", `{"type":"text","sessionID":"ses_2","part":{"text":"done"}}
{"type":"step_finish","sessionID":"ses_1","part":{"reason":"stop"}}`, false},
		{"screen claim", "opencode", "Completed successfully", false},
		{"pi settled", "pi", `{"type":"session","id":"p1"}
{"type":"message_end","message":{"role":"assistant","stopReason":"stop","content":[{"type":"text","text":"done"}]}}
{"type":"agent_settled","aborted":false}`, true},
		{"pi agent end insufficient", "pi", `{"type":"session","id":"p1"}
{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}
{"type":"agent_end"}`, false},
		{"pi live tool", "pi", `{"type":"session","id":"p1"}
{"type":"tool_execution_start","toolCallId":"t1"}
{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}
{"type":"agent_settled","aborted":false}`, false},
		{"pi abort", "pi", `{"type":"session","id":"p1"}
{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}
{"type":"agent_settled","aborted":true}`, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			p := newStructuredOutput(c.kind, "")
			for _, b := range []byte(c.stream) {
				p.Write([]byte{b})
			}
			p.finish()
			if (p.validate() == nil) != c.success {
				t.Fatalf("unexpected validation: %v", p.validate())
			}
		})
	}
}
func TestStructuredContinuationBindsProviderAndPreservesUnicode(t *testing.T) {
	p := newStructuredOutput("pi", "expected")
	p.Write([]byte("{\"type\":\"session\",\"id\":\"expected\"}\n{\"type\":\"message_end\",\"message\":{\"role\":\"assistant\",\"stopReason\":\"stop\",\"content\":[{\"type\":\"text\",\"text\":\"before\u2028after\"}]}}\n{\"type\":\"agent_settled\",\"aborted\":false}\n"))
	p.finish()
	if p.validate() != nil || !strings.Contains(p.text.String(), "before\u2028after") {
		t.Fatal(p.validate(), p.text.String())
	}
	p.Write([]byte("{\"type\":\"session\",\"id\":\"other\"}\n"))
	if p.validate() == nil {
		t.Fatal("accepted wrong native conversation")
	}
}
func TestStructuredCLIExitAndCancelOverrideOptimisticEvents(t *testing.T) {
	for _, kind := range []string{"opencode", "pi"} {
		t.Run(kind, func(t *testing.T) {
			s := testService(t)
			dir := t.TempDir()
			stream := `{"type":"text","sessionID":"ses_1","part":{"text":"done"}}
{"type":"step_finish","sessionID":"ses_1","part":{"reason":"stop"}}`
			if kind == "pi" {
				stream = `{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"done"}]}}
{"type":"agent_settled","aborted":false}`
			}
			bin := filepath.Join(dir, kind)
			if err := os.WriteFile(bin, []byte("#!/bin/sh\nprintf '%s\\n' "+quote(stream)+"\nexit 7\n"), 0700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", dir+string(os.PathListSeparator)+os.Getenv("PATH"))
			spec := Spec{Executor: kind, Prompt: "test", TimeoutSeconds: 10}
			receipt := Receipt{Workspace: &Workspace{Directory: dir}, DeadlineMS: executionDeadline(10)}
			r, _ := s.structuredProcess(context.Background(), dir, spec, receipt, "", io.Discard, io.Discard)
			if r.State != "failed" || r.ExitCode != 7 {
				t.Fatalf("%+v", r)
			}
			if err := writeJSON(filepath.Join(dir, "cancel.json"), map[string]bool{"cancel": true}); err != nil {
				t.Fatal(err)
			}
			r, _ = s.structuredProcess(context.Background(), dir, spec, receipt, "", io.Discard, io.Discard)
			if r.State != "cancelled" {
				t.Fatalf("%+v", r)
			}
		})
	}
}

func TestUnconfirmedNativeIdentityIsNotPublishedAsASessionBinding(t *testing.T) {
	s := testService(t)
	dir, _ := s.directory("pending-provider")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	receipt := Receipt{State: "running", Session: "owned", Binding: &SessionBinding{ID: "owned"}}
	if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(filepath.Join(dir, "result.json"), Result{State: "failed", Summary: "before native session creation"}); err != nil {
		t.Fatal(err)
	}
	status, err := s.Status("pending-provider")
	if err != nil || status.Binding != nil || status.Session != "owned" || status.Result == nil {
		t.Fatal(status, err)
	}
	receipt.Binding.ProviderID = "confirmed"
	if err = writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		t.Fatal(err)
	}
	status, err = s.Status("pending-provider")
	if err != nil || status.Binding == nil || status.Binding.ProviderID != "confirmed" {
		t.Fatal(status, err)
	}
}
