package agentexecution

import (
	"encoding/json"
	"testing"
)

func claudeCompactEvent(t *testing.T) SessionEvent {
	t.Helper()
	var event SessionEvent
	if err := json.Unmarshal([]byte(`{"hook_event_name":"SessionStart","source":"compact","session_id":"provider-thread"}`), &event); err != nil {
		t.Fatal(err)
	}
	return event
}

func TestClaudeCompactionPreservesAuthenticatedTurn(t *testing.T) {
	for _, scenario := range []string{"busy", "same-prompt", "pending-tool", "repeated", "idle"} {
		t.Run(scenario, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedClaudeSession(t, s, binding)
			spec := startClaudeTask(t, s, binding, "claude-compact")
			path, _ := s.lifecycleFile(binding)
			var before sessionLifecycle
			if err := readJSON(path, &before); err != nil {
				t.Fatal(err)
			}
			compact := claudeCompactEvent(t)
			if scenario == "same-prompt" {
				compact.PromptID = "task-prompt"
			}
			tool := claudeEvent("PreToolUse", "task-prompt")
			tool.ToolID = "pending-command"
			if scenario == "pending-tool" {
				if err := s.applySessionEvent("claude", binding, tool); err != nil {
					t.Fatal(err)
				}
			}
			stop := claudeEvent("Stop", "task-prompt")
			stop.StopAssistant = "Verified after compaction"
			idle := claudeEvent("Notification", "task-prompt")
			idle.NotificationType = "idle_prompt"
			if scenario == "idle" {
				for _, event := range []SessionEvent{stop, idle} {
					if err := s.applySessionEvent("claude", binding, event); err != nil {
						t.Fatal(err)
					}
				}
				before = sessionLifecycle{}
				if err := readJSON(path, &before); err != nil {
					t.Fatal(err)
				}
			}
			for count := 0; count < 2; count++ {
				if err := s.applySessionEvent("claude", binding, compact); err != nil {
					t.Fatal(err)
				}
				var after sessionLifecycle
				if err := readJSON(path, &after); err != nil {
					t.Fatal(err)
				}
				if after.State != before.State || after.TurnID != before.TurnID || after.PromptHash != before.PromptHash || after.LaunchKey != before.LaunchKey || after.Binding.ProviderID != before.Binding.ProviderID || after.CompletedKey != before.CompletedKey {
					t.Fatalf("compaction changed authenticated lifecycle: before=%+v after=%+v", before, after)
				}
				if scenario == "pending-tool" && !after.Tools[tool.ToolID] {
					t.Fatal("compaction cleared an unfinished command")
				}
				if scenario != "repeated" {
					break
				}
			}
			if scenario == "pending-tool" {
				tool.Hook = "PostToolUse"
				if err := s.applySessionEvent("claude", binding, tool); err != nil {
					t.Fatal(err)
				}
			}
			if scenario != "idle" {
				status, err := s.Status(spec.Key)
				if err != nil || status.Result != nil {
					t.Fatalf("compaction completed work without Stop and idle: %+v %v", status, err)
				}
				for _, event := range []SessionEvent{stop, idle} {
					if err := s.applySessionEvent("claude", binding, event); err != nil {
						t.Fatal(err)
					}
				}
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.State != "succeeded" || status.Result == nil || status.Result.Summary != stop.StopAssistant {
				t.Fatalf("compacted turn did not settle with original identity: %+v %v", status, err)
			}
		})
	}
}

func TestClaudeCompactionCannotReplaceStopOrSessionIdentity(t *testing.T) {
	for _, scenario := range []string{"startup", "resume", "clear", "fork", "missing-source", "wrong-provider", "wrong-prompt", "interrupted", "pending-tool", "missing-registry", "background-work", "scheduled-wakeup", "missing-authenticated-turn", "missing-authenticated-prompt", "submitting", "stale-stop"} {
		t.Run(scenario, func(t *testing.T) {
			s, binding := sessionFixture(t)
			seedClaudeSession(t, s, binding)
			spec := startClaudeTask(t, s, binding, "claude-compact-negative")
			compact := claudeCompactEvent(t)
			stop := claudeEvent("Stop", "task-prompt")
			stop.StopAssistant = "Must not publish"
			switch scenario {
			case "startup", "resume", "clear", "fork", "missing-source":
				source := scenario
				if scenario == "missing-source" {
					source = ""
				}
				data, _ := json.Marshal(map[string]string{"hook_event_name": "SessionStart", "session_id": "provider-thread", "source": source})
				if err := json.Unmarshal(data, &compact); err != nil {
					t.Fatal(err)
				}
			case "wrong-provider":
				compact.ProviderID = "another-provider"
			case "wrong-prompt":
				compact.PromptID = "another-prompt"
			case "interrupted":
				if err := s.applySessionEvent("claude", binding, claudeEvent("Interrupt", "task-prompt")); err != nil {
					t.Fatal(err)
				}
			case "pending-tool":
				tool := claudeEvent("PreToolUse", "task-prompt")
				tool.ToolID = "still-running"
				if err := s.applySessionEvent("claude", binding, tool); err != nil {
					t.Fatal(err)
				}
			case "missing-registry":
				stop.BackgroundTasks = nil
			case "background-work":
				stop.BackgroundTasks = []json.RawMessage{json.RawMessage(`{"id":"active"}`)}
			case "scheduled-wakeup":
				stop.SessionCrons = []json.RawMessage{json.RawMessage(`{"id":"scheduled"}`)}
			case "missing-authenticated-turn", "missing-authenticated-prompt", "submitting":
				path, _ := s.lifecycleFile(binding)
				var state sessionLifecycle
				if err := readJSON(path, &state); err != nil {
					t.Fatal(err)
				}
				switch scenario {
				case "missing-authenticated-turn":
					state.TurnID = ""
				case "missing-authenticated-prompt":
					state.PromptHash = ""
				case "submitting":
					state.State = "submitting"
				}
				if err := writeJSON(path, state); err != nil {
					t.Fatal(err)
				}
			case "stale-stop":
				if err := s.applySessionEvent("claude", binding, stop); err != nil {
					t.Fatal(err)
				}
			}
			if err := s.applySessionEvent("claude", binding, compact); err != nil {
				t.Fatal(err)
			}
			if scenario != "stale-stop" {
				if err := s.applySessionEvent("claude", binding, stop); err != nil {
					t.Fatal(err)
				}
			}
			idle := claudeEvent("Notification", "task-prompt")
			idle.NotificationType = "idle_prompt"
			if err := s.applySessionEvent("claude", binding, idle); err != nil {
				t.Fatal(err)
			}
			status, err := s.Status(spec.Key)
			if err != nil || status.Result != nil {
				t.Fatalf("unproven compacted turn published: %+v %v", status, err)
			}
		})
	}
}
