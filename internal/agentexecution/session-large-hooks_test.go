package agentexecution

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestLargePostToolUseResponseDoesNotLoseCompletionAndReportedFiles(t *testing.T) {
	for _, hook := range []string{"PostToolUse", "PostToolUseFailure"} {
		t.Run(hook, func(t *testing.T) {
			service, binding := sessionFixture(t)
			seedClaudeSession(t, service, binding)
			spec := startClaudeTask(t, service, binding, "large-hook")
			event := claudeEvent("PreToolUse", "task-prompt")
			event.ToolID = "read-page"
			if err := service.applySessionEvent("claude", binding, event); err != nil {
				t.Fatal(err)
			}
			unit, repeat := "page content", 20000
			if path := os.Getenv("ROAMI_CASE61_INPUT"); path != "" {
				var recipe struct {
					Response struct {
						Unit   string `json:"unit"`
						Repeat int    `json:"repeat"`
					} `json:"large_response_recipe"`
				}
				if err := readJSON(path, &recipe); err != nil {
					t.Fatal(err)
				}
				unit, repeat = recipe.Response.Unit, recipe.Response.Repeat
				if unit == "" || repeat < 1 || repeat > 1000000 {
					t.Fatal("Invalid Case response recipe")
				}
			}
			payload := map[string]any{"hook_event_name": hook, "session_id": "provider-thread", "prompt_id": "task-prompt", "tool_use_id": "read-page", "tool_response": map[string]string{"content": strings.Repeat(unit, repeat)}}
			raw, err := json.Marshal(payload)
			if err != nil {
				t.Fatal(err)
			}
			if len(raw) <= 100000 {
				t.Fatal("Case input did not reproduce the oversized callback")
			}
			decoded, err := ReadSessionEvent(strings.NewReader(string(raw)))
			if err != nil {
				t.Fatalf("large tool response lost its completion: %v", err)
			}
			if err = service.applySessionEvent("claude", binding, decoded); err != nil {
				t.Fatal(err)
			}
			stop := claudeEvent("Stop", "task-prompt")
			stop.StopAssistant = "Report: [page](report/index.html)"
			if err = service.applySessionEvent("claude", binding, stop); err != nil {
				t.Fatal(err)
			}
			idle := claudeEvent("Notification", "task-prompt")
			idle.NotificationType = "idle_prompt"
			if err = service.applySessionEvent("claude", binding, idle); err != nil {
				t.Fatal(err)
			}
			status, err := service.Status(spec.Key)
			if err != nil || status.Result == nil || status.State != "succeeded" || status.Result.Summary != stop.StopAssistant {
				t.Fatalf("completion not retained: %+v %v", status, err)
			}
		})
	}
}

func TestSessionHookMetadataAndJSONRemainBounded(t *testing.T) {
	for _, raw := range []string{`{"prompt":"` + strings.Repeat("x", 100001) + `"}`, `{"session_id":"id"} {"session_id":"other"}`, `{"tool_response":`, strings.Repeat(" ", 64<<20) + `{}`} {
		if _, err := ReadSessionEvent(strings.NewReader(raw)); err == nil {
			t.Fatal("invalid hook accepted")
		}
	}
}

func TestSessionEventDecoderDropsLargeUnusedResponseBeforeMetadataLimit(t *testing.T) {
	input := `{"hook_event_name":"PostToolUse","session_id":"id","prompt_id":"turn","tool_use_id":"read","tool_response":"` + strings.Repeat("x", 200000) + `"}`
	event, err := DecodeSessionEvent([]byte(input))
	if err != nil || event.ToolID != "read" || event.PromptID != "turn" {
		t.Fatalf("event lost: %+v %v", event, err)
	}
	// Ensure the ordinary file-backed entry receives the same exact envelope.
	path := filepath.Join(t.TempDir(), "event.json")
	if err = os.WriteFile(path, []byte(input), 0600); err != nil {
		t.Fatal(err)
	}
	file, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer file.Close()
	if _, err = ReadSessionEvent(file); err != nil {
		t.Fatal(err)
	}
}
