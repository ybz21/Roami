package agentexecution

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func claudeEvent(hook, prompt string) SessionEvent {
	return SessionEvent{Hook: hook, ProviderID: "provider-thread", PromptID: prompt, BackgroundTasks: []json.RawMessage{}, SessionCrons: []json.RawMessage{}}
}

func seedClaudeSession(t *testing.T, s Service, binding SessionBinding) {
	t.Helper()
	prompt := claudeEvent("UserPromptSubmit", "seed-prompt")
	prompt.Prompt = "manual question"
	stop := claudeEvent("Stop", "seed-prompt")
	stop.StopAssistant = "Ready"
	idle := claudeEvent("Notification", "seed-prompt")
	idle.NotificationType = "idle_prompt"
	for _, event := range []SessionEvent{prompt, stop, idle} {
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
}

func startClaudeTask(t *testing.T, s Service, binding SessionBinding, key string) Spec {
	t.Helper()
	spec := Spec{Key: key, Executor: "claude", SessionID: binding.ID, Prompt: "Follow up with evidence", TimeoutSeconds: 120}
	if _, err := s.Launch(context.Background(), spec); err != nil {
		t.Fatal(err)
	}
	prompt, _ := os.ReadFile(filepath.Join(s.Runtime.DataDir, "prompt"))
	event := claudeEvent("UserPromptSubmit", "task-prompt")
	event.Prompt = string(prompt)
	if err := s.applySessionEvent("claude", binding, event); err != nil {
		t.Fatal(err)
	}
	return spec
}

func TestClaudeNeedsStopThenMatchingIdleAndRetainsOriginalSession(t *testing.T) {
	s, binding := sessionFixture(t)
	seedClaudeSession(t, s, binding)
	spec := startClaudeTask(t, s, binding, "claude-completion")
	stop := claudeEvent("Stop", "task-prompt")
	stop.StopAssistant = "Checked result"
	if err := s.applySessionEvent("claude", binding, stop); err != nil {
		t.Fatal(err)
	}
	status, err := s.Status(spec.Key)
	if err != nil || status.State != "running" || status.Result != nil {
		t.Fatalf("Stop settled a turn: %+v %v", status, err)
	}
	idle := claudeEvent("Notification", "task-prompt")
	idle.NotificationType = "idle_prompt"
	if err := s.applySessionEvent("claude", binding, idle); err != nil {
		t.Fatal(err)
	}
	status, err = s.Status(spec.Key)
	if err != nil || status.Result == nil || status.State != "succeeded" || status.Result.Summary != "Checked result" || status.Binding.ProviderID != "provider-thread" {
		t.Fatalf("idle evidence: %+v %v", status, err)
	}
	finished := status.Result.FinishedMS
	if err := s.applySessionEvent("claude", binding, idle); err != nil {
		t.Fatal(err)
	}
	status, err = s.Status(spec.Key)
	if err != nil || status.Result.FinishedMS != finished {
		t.Fatal("duplicate idle rewrote completion")
	}
}

func TestClaudeNeverSettlesWithoutCompleteQuiescenceEvidence(t *testing.T) {
	for _, scenario := range []string{"idle-only", "missing-registry", "null-registry", "background-task", "scheduled-wakeup", "wrong-prompt", "later-tool", "tool-in-flight", "stop-failure", "subagent-stop", "subagent-text", "missing-prompt-id"} {
		t.Run(scenario, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedClaudeSession(t, s, binding)
			spec := startClaudeTask(t, s, binding, "claude-uncertain")
			stop := claudeEvent("Stop", "task-prompt")
			stop.StopAssistant = "must not publish"
			idle := claudeEvent("Notification", "task-prompt")
			idle.NotificationType = "idle_prompt"
			switch scenario {
			case "missing-registry":
				stop.BackgroundTasks = nil
			case "null-registry":
				stop.SessionCrons = nil
			case "background-task":
				stop.BackgroundTasks = []json.RawMessage{json.RawMessage(`{"id":"background","status":"running"}`)}
			case "scheduled-wakeup":
				stop.SessionCrons = []json.RawMessage{json.RawMessage(`{"id":"cron"}`)}
			case "wrong-prompt":
				idle.PromptID = "other-prompt"
			case "stop-failure":
				stop.Hook = "StopFailure"
			case "subagent-stop":
				stop.Hook = "SubagentStop"
				stop.AgentID = "child"
			case "subagent-text":
				stop.AgentID = "child"
			case "missing-prompt-id":
				stop.PromptID = ""
			}
			tool := claudeEvent("PreToolUse", "task-prompt")
			tool.ToolID = "tool"
			if scenario == "tool-in-flight" {
				if err := s.applySessionEvent("claude", binding, tool); err != nil {
					t.Fatal(err)
				}
			}
			if scenario != "idle-only" {
				err := s.applySessionEvent("claude", binding, stop)
				if (err != nil) != (scenario == "missing-prompt-id") {
					t.Fatalf("stop error: %v", err)
				}
			}
			if scenario == "later-tool" {
				if err := s.applySessionEvent("claude", binding, tool); err != nil {
					t.Fatal(err)
				}
				tool.Hook = "PostToolUse"
				if err := s.applySessionEvent("claude", binding, tool); err != nil {
					t.Fatal(err)
				}
			}
			if err := s.applySessionEvent("claude", binding, idle); err != nil {
				t.Fatal(err)
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.Result != nil {
				t.Fatalf("uncertain turn published: %+v %v", status, err)
			}
		})
	}
}

func TestClaudeStopBlockedByOtherHooksRequiresLaterFinalStop(t *testing.T) {
	s, binding := sessionFixture(t)
	seedClaudeSession(t, s, binding)
	spec := startClaudeTask(t, s, binding, "claude-continued-stop")
	first := claudeEvent("Stop", "task-prompt")
	first.StopAssistant = "old answer"
	tool := claudeEvent("PreToolUse", "task-prompt")
	tool.ToolID = "continued-tool"
	after := tool
	after.Hook = "PostToolUseFailure"
	final := claudeEvent("Stop", "task-prompt")
	final.StopAssistant = "updated answer"
	idle := claudeEvent("Notification", "task-prompt")
	idle.NotificationType = "idle_prompt"
	for _, event := range []SessionEvent{first, tool, after, final, idle} {
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
	status, err := s.Status(spec.Key)
	if err != nil || status.Result == nil || status.Result.Summary != "updated answer" {
		t.Fatalf("stale Stop summary: %+v %v", status, err)
	}
}

func TestClaudeCancellationStillNeedsIdleAndStopProof(t *testing.T) {
	s, binding := sessionFixture(t)
	seedClaudeSession(t, s, binding)
	spec := startClaudeTask(t, s, binding, "claude-cancel")
	if _, err := s.Cancel(spec.Key); err != nil {
		t.Fatal(err)
	}
	tool := claudeEvent("PreToolUse", "task-prompt")
	tool.ToolID = "denied-tool"
	if err := s.applySessionEvent("claude", binding, tool); err == nil || err.Error() != "SESSION_TASK_CANCEL_REQUESTED" {
		t.Fatalf("cancel admitted another tool: %v", err)
	}
	stop := claudeEvent("Stop", "task-prompt")
	stop.StopAssistant = "Stopped"
	idle := claudeEvent("Notification", "task-prompt")
	idle.NotificationType = "idle_prompt"
	for _, event := range []SessionEvent{stop, idle} {
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
	status, err := s.Status(spec.Key)
	if err != nil || status.Result == nil || status.State != "cancelled" {
		t.Fatalf("cancel completion: %+v %v", status, err)
	}
}

func TestClaudeIdleCannotSettleWhileTaskProcessSurvives(t *testing.T) {
	s, binding := sessionFixture(t)
	seedClaudeSession(t, s, binding)
	spec := startClaudeTask(t, s, binding, "claude-background-process")
	child := exec.Command("sleep", "30")
	if err := child.Start(); err != nil {
		t.Fatal(err)
	}
	defer func() { _ = child.Process.Kill(); _ = child.Wait() }()
	stop := claudeEvent("Stop", "task-prompt")
	idle := claudeEvent("Notification", "task-prompt")
	idle.NotificationType = "idle_prompt"
	for _, event := range []SessionEvent{stop, idle} {
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
	status, err := s.Status(spec.Key)
	if err != nil || status.Result != nil || status.State != "unknown" {
		t.Fatalf("live process settled: %+v %v", status, err)
	}
}

func TestClaudeManualTakeoverFencesOldStopAndIdle(t *testing.T) {
	s, binding := sessionFixture(t)
	seedClaudeSession(t, s, binding)
	spec := startClaudeTask(t, s, binding, "claude-manual-takeover")
	stop := claudeEvent("Stop", "task-prompt")
	stop.StopAssistant = "old task"
	takeover := claudeEvent("UserPromptSubmit", "manual-prompt")
	takeover.Prompt = "new manual request"
	idle := claudeEvent("Notification", "task-prompt")
	idle.NotificationType = "idle_prompt"
	for _, event := range []SessionEvent{stop, takeover, idle} {
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
	status, err := s.Status(spec.Key)
	if err != nil || status.Result != nil {
		t.Fatalf("manual takeover published old result: %+v %v", status, err)
	}
}

func TestClaudeMalformedHookInvalidatesEarlierStopCandidate(t *testing.T) {
	s, binding := sessionFixture(t)
	seedClaudeSession(t, s, binding)
	spec := startClaudeTask(t, s, binding, "claude-missing-hook-identity")
	stop := claudeEvent("Stop", "task-prompt")
	stop.StopAssistant = "stale answer"
	if err := s.applySessionEvent("claude", binding, stop); err != nil {
		t.Fatal(err)
	}
	failure := claudeEvent("StopFailure", "")
	if err := s.applySessionEvent("claude", binding, failure); err == nil {
		t.Fatal("missing prompt identity accepted")
	}
	idle := claudeEvent("Notification", "task-prompt")
	idle.NotificationType = "idle_prompt"
	if err := s.applySessionEvent("claude", binding, idle); err != nil {
		t.Fatal(err)
	}
	status, err := s.Status(spec.Key)
	if err != nil || status.Result != nil {
		t.Fatalf("malformed hook preserved stale candidate: %+v %v", status, err)
	}
}
