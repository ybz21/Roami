package agentexecution

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func claudeNotificationRecord(binding SessionBinding, prompt string) map[string]any {
	return map[string]any{"type": "attachment", "sessionId": binding.ProviderID, "cwd": binding.Directory, "attachment": map[string]any{
		"type": "queued_command", "prompt": prompt, "commandMode": "task-notification",
		"origin": map[string]any{"kind": "task-notification", "producer": "session-task"},
	}}
}

func TestClaudeTaskNotificationRequiresBoundProviderProvenance(t *testing.T) {
	for _, mode := range []string{"valid", "earlier conversation", "wrong provider", "wrong turn", "new user", "copied notice", "queued user", "different notice", "wrong prompt hash", "wrong directory", "missing origin", "human origin", "scheduled trigger", "wrong producer", "unmanaged", "unknown lifecycle", "provider conflict", "sidechain", "malformed", "writable", "symlink"} {
		t.Run(mode, func(t *testing.T) {
			binding, path, _, prompt := reportFixture(t)
			notice := "<task-notification><task-id>background</task-id><status>completed</status></task-notification>"
			state := sessionLifecycle{Binding: binding, Executor: "claude", State: "busy", LaunchKey: "task", TurnID: "prompt", PromptHash: workspaceHash(prompt)}
			event := SessionEvent{Hook: "UserPromptSubmit", ProviderID: binding.ProviderID, TurnID: "prompt", Prompt: notice}
			records := reportRecords(binding, prompt)[:1]
			records = append(records, claudeNotificationRecord(binding, notice))
			attachment := records[1]["attachment"].(map[string]any)
			origin := attachment["origin"].(map[string]any)
			switch mode {
			case "earlier conversation":
				records = append([]map[string]any{{"type": "user", "sessionId": binding.ProviderID, "promptId": "previous", "message": map[string]any{"content": "Earlier question"}}}, records...)
			case "wrong provider":
				event.ProviderID = "foreign"
			case "wrong turn":
				event.TurnID = "new-prompt"
			case "new user", "copied notice":
				text := "A new user instruction"
				if mode == "copied notice" {
					text = notice
				}
				records = append(records, map[string]any{"type": "user", "sessionId": binding.ProviderID, "promptId": "new-prompt", "message": map[string]any{"content": text}})
			case "queued user":
				record := claudeNotificationRecord(binding, "A new user instruction")
				record["attachment"].(map[string]any)["origin"] = map[string]any{"kind": "human"}
				records = append(records, record)
			case "different notice":
				event.Prompt = "Another notice"
			case "wrong prompt hash":
				state.PromptHash = workspaceHash("different task")
			case "wrong directory":
				records[1]["cwd"] = t.TempDir()
			case "missing origin":
				delete(attachment, "origin")
			case "human origin":
				origin["kind"] = "human"
			case "scheduled trigger":
				origin["subkind"] = "scheduled-trigger"
			case "wrong producer":
				origin["producer"] = "external"
			case "unmanaged":
				state.LaunchKey = ""
			case "unknown lifecycle":
				state.State = "unknown"
			case "provider conflict":
				state.ProviderConflict = &sessionProviderConflict{ProviderID: "foreign"}
			case "sidechain":
				records[1]["isSidechain"] = true
			}
			writeReportRecords(t, path, records)
			switch mode {
			case "malformed":
				if err := os.WriteFile(path, []byte("{"), 0600); err != nil {
					t.Fatal(err)
				}
			case "writable":
				if err := os.Chmod(path, 0666); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.Rename(path, path+".real"); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(path+".real", path); err != nil {
					t.Fatal(err)
				}
			}
			want := mode == "valid" || mode == "earlier conversation"
			if got := claudeTaskNotification(state, event); got != want {
				t.Fatalf("notification authenticated = %v, want %v", got, want)
			}
		})
	}
}

func TestClaudeBackgroundNotificationPreservesTaskUntilStopAndIdle(t *testing.T) {
	s, binding := sessionFixture(t)
	seedClaudeSession(t, s, binding)
	spec := startClaudeTask(t, s, binding, "claude-notification")
	path, _ := s.lifecycleFile(binding)
	var state sessionLifecycle
	if err := readJSON(path, &state); err != nil {
		t.Fatal(err)
	}
	state.Binding.ProviderID = reportProviderID
	providerHome := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", providerHome)
	transcript := filepath.Join(providerHome, "projects", "workspace", reportProviderID+".jsonl")
	if err := os.MkdirAll(filepath.Dir(transcript), 0700); err != nil {
		t.Fatal(err)
	}
	tool := claudeEvent("PreToolUse", state.TurnID)
	tool.ProviderID, tool.ToolID = reportProviderID, "background-launch"
	if err := writeJSON(path, state); err != nil {
		t.Fatal(err)
	}
	dir, _ := s.directory(spec.Key)
	var receipt Receipt
	if err := readJSON(filepath.Join(dir, "receipt.json"), &receipt); err != nil {
		t.Fatal(err)
	}
	receipt.Binding.ProviderID = reportProviderID
	if err := writeJSON(filepath.Join(dir, "receipt.json"), receipt); err != nil {
		t.Fatal(err)
	}
	if err := s.applySessionEvent("claude", binding, tool); err != nil {
		t.Fatal(err)
	}
	if err := readJSON(path, &state); err != nil {
		t.Fatal(err)
	}
	notice := "<task-notification><task-id>background</task-id><status>completed</status></task-notification>"
	writeReportRecords(t, transcript, []map[string]any{
		{"type": "user", "sessionId": reportProviderID, "promptId": state.TurnID, "cwd": binding.Directory, "message": map[string]any{"content": sessionPrompt(dir, spec)}},
		claudeNotificationRecord(state.Binding, notice),
	})
	notification := claudeEvent("UserPromptSubmit", state.TurnID)
	notification.ProviderID, notification.Prompt = reportProviderID, notice
	for i := 0; i < 2; i++ {
		if err := s.applySessionEvent("claude", binding, notification); err != nil {
			t.Fatal(err)
		}
	}
	var after sessionLifecycle
	if err := readJSON(path, &after); err != nil || !reflect.DeepEqual(after, state) {
		t.Fatalf("background notice changed task binding or tools: %+v %v", after, err)
	}
	if status, err := s.Status(spec.Key); err != nil || status.Result != nil || status.State != "running" {
		t.Fatalf("notification completed task: %+v %v", status, err)
	}
	stop := claudeEvent("Stop", state.TurnID)
	stop.ProviderID, stop.StopAssistant = reportProviderID, "Verified report"
	idle := claudeEvent("Notification", state.TurnID)
	idle.ProviderID, idle.NotificationType = reportProviderID, "idle_prompt"
	tool.Hook = "PostToolUseFailure"
	for _, event := range []SessionEvent{tool, stop, notification} {
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
	if err := readJSON(path, &after); err != nil || after.ClaudeStop != nil || after.State != "busy" {
		t.Fatalf("notification retained a stale Stop: %+v %v", after, err)
	}
	probe := after
	probeIdle := idle
	probeIdle.TurnID = idle.PromptID
	if _, completed := observeClaudeStop(&probe, &probeIdle); completed {
		t.Fatal("idle completed work using a Stop from before the notification")
	}
	for _, event := range []SessionEvent{stop, idle} {
		if err := s.applySessionEvent("claude", binding, event); err != nil {
			t.Fatal(err)
		}
	}
	if status, err := s.Status(spec.Key); err != nil || status.Result == nil || status.State != "succeeded" || status.Result.Summary != stop.StopAssistant {
		t.Fatalf("task failed to settle after notification: %+v %v", status, err)
	}
}
