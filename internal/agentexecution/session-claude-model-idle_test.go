package agentexecution

import (
	"encoding/json"
	"testing"
)

func TestClaudeIdleModelSelectionRequiresSameModelAndNoNewWork(t *testing.T) {
	binding := SessionBinding{ProviderID: "provider", Directory: "/project"}
	user := func(id, text string) map[string]any {
		return map[string]any{"type": "user", "sessionId": "provider", "cwd": "/project", "promptId": id, "message": map[string]any{"content": text}}
	}
	caveat := user("picker", claudeLocalCommandCaveat)
	caveat["isMeta"] = true
	records := []map[string]any{user("task", "initial input"), {"type": "assistant", "sessionId": "provider", "cwd": "/project", "timestamp": "2026-11-18T00:00:00Z", "message": map[string]any{"content": []any{map[string]any{"type": "text", "text": "Ready"}}}}, caveat, user("picker", "<command-name>/model</command-name>\n <command-message>model</command-message>\n <command-args></command-args>"), user("picker", "<local-command-stdout>Set model to `free` and saved as your default for new sessions</local-command-stdout>"), {"type": "cost-state", "sessionId": "provider"}}
	encode := func(rs []map[string]any) []byte {
		var data []byte
		for _, r := range rs {
			b, err := json.Marshal(r)
			if err != nil {
				t.Fatal(err)
			}
			data = append(data, b...)
			data = append(data, '\n')
		}
		return data
	}
	verify := func(data []byte) bool {
		return claudeSameModelSuffix(data, binding, "task", workspaceHash("initial input"), "Ready", "free", 1794960001000)
	}
	if !verify(encode(records)) {
		t.Fatal("same-model local command rejected")
	}
	wrapped := append([]map[string]any{}, records...)
	wrapped[0] = user("task", "\n\n<pasted_content id=\"fixture\">\ninitial input\n</pasted_content id=\"fixture\">\n")
	if !verify(encode(wrapped)) {
		t.Fatal("same-model local command after an exact wrapped input rejected")
	}
	wrapped[0] = user("task", "\n\n<pasted_content id=\"fixture\">\nchanged input\n</pasted_content id=\"fixture\">\n")
	if verify(encode(wrapped)) {
		t.Fatal("changed wrapped input accepted")
	}
	for _, name := range []string{"different model", "new user", "tool activity", "new request", "partial picker", "foreign provider", "invalid JSON"} {
		t.Run(name, func(t *testing.T) {
			rs := append([]map[string]any{}, records...)
			switch name {
			case "different model":
				rs[4] = user("picker", "<local-command-stdout>Set model to `paid`</local-command-stdout>")
			case "new user":
				rs = append(rs, user("new", "do work"))
			case "tool activity":
				rs = append(rs, map[string]any{"type": "assistant", "sessionId": "provider", "message": map[string]any{"content": []any{map[string]any{"type": "tool_use", "name": "Bash"}}}})
			case "new request":
				rs = append(rs, map[string]any{"type": "api-request"})
			case "partial picker":
				rs = rs[:4]
			case "foreign provider":
				rs = append(rs, map[string]any{"type": "cost-state", "sessionId": "other"})
			}
			data := encode(rs)
			if name == "invalid JSON" {
				data = append(data, '{')
			}
			if verify(data) {
				t.Fatal("unproven idle accepted")
			}
		})
	}
}
