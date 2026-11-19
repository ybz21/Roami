package agentexecution

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestClaudeNativeIdleRequiresSameTurnStopAndActualModel(t *testing.T) {
	state := sessionLifecycle{Executor: "claude", Model: "free", State: "idle", TurnID: "human-turn", PromptHash: workspaceHash("continue"), Binding: SessionBinding{ProviderID: "provider", Directory: "/project"}}
	state.ClaudeStop = &claudeStop{PromptID: state.TurnID, PromptHash: state.PromptHash, Summary: "Done", Idle: true}
	var data []byte
	for _, record := range []map[string]any{
		{"type": "user", "sessionId": "provider", "cwd": "/project", "promptId": "human-turn", "message": map[string]any{"content": "continue"}},
		{"type": "api-request-shape", "sessionId": "provider", "cwd": "/project"},
		{"type": "assistant", "sessionId": "provider", "cwd": "/project", "message": map[string]any{"model": "roami-claude/free", "content": "Done", "stop_reason": "end_turn"}},
	} {
		b, _ := json.Marshal(record)
		data = append(data, append(b, '\n')...)
	}
	if !claudeNativeIdleEvidence(data, state) {
		t.Fatal("authenticated native idle rejected")
	}
	for _, name := range []string{"model", "new input", "wrong provider", "missing idle", "wrong stop", "pending tool", "active launch", "partial", "later shape"} {
		t.Run(name, func(t *testing.T) {
			s, stop, input := state, *state.ClaudeStop, string(data)
			s.ClaudeStop = &stop
			switch name {
			case "model":
				input = strings.ReplaceAll(input, "roami-claude/free", "paid")
			case "new input":
				input += `{"type":"user","message":{"content":"new"}}` + "\n"
			case "wrong provider":
				input = strings.ReplaceAll(input, "provider", "other")
			case "missing idle":
				stop.Idle = false
			case "wrong stop":
				stop.PromptID = "old"
			case "pending tool":
				s.Tools = map[string]bool{"tool": true}
			case "active launch":
				s.LaunchKey = "running"
			case "later shape":
				input += `{"type":"api-request-shape","sessionId":"provider","cwd":"/project"}` + "\n"
			case "partial":
				input = strings.TrimSuffix(input, "\n")
			}
			if claudeNativeIdleEvidence([]byte(input), s) {
				t.Fatal("unconfirmed native idle accepted")
			}
		})
	}
}
