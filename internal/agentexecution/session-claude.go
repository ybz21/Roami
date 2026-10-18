package agentexecution

import "strings"

type claudeStop struct {
	PromptID   string `json:"promptId"`
	PromptHash string `json:"promptHash"`
	Summary    string `json:"summary"`
}

// Stop can be blocked by another hook. Only a later matching idle notification settles it.
func observeClaudeStop(state *sessionLifecycle, event *SessionEvent) (handled, completed bool) {
	switch event.Hook {
	case "Stop":
		state.ClaudeStop = nil
		if state.State != "busy" || event.TurnID != state.TurnID || event.BackgroundTasks == nil || event.SessionCrons == nil || len(event.BackgroundTasks) != 0 || len(event.SessionCrons) != 0 {
			return true, false
		}
		for tool := range state.Tools {
			if !strings.HasPrefix(tool, "subagent:") {
				return true, false
			}
		}
		state.ClaudeStop = &claudeStop{PromptID: event.TurnID, PromptHash: state.PromptHash, Summary: truncate(event.StopAssistant, 32000)}
		return true, false
	case "SubagentStop":
		return true, false
	case "StopFailure":
		state.ClaudeStop, state.State = nil, "unknown"
		return true, false
	case "Notification":
		if event.NotificationType != "idle_prompt" {
			return true, false
		}
		if state.State == "idle" && event.TurnID == state.TurnID {
			return true, false
		}
		candidate := state.ClaudeStop
		if state.State != "busy" || candidate == nil || candidate.PromptID != event.TurnID || candidate.PromptID != state.TurnID || candidate.PromptHash != state.PromptHash {
			state.State = "unknown"
			return true, false
		}
		for tool := range state.Tools {
			if !strings.HasPrefix(tool, "subagent:") {
				state.State = "unknown"
				return true, false
			}
		}
		for tool := range state.Tools {
			delete(state.Tools, tool)
		}
		event.LastAssistant = candidate.Summary
		state.ClaudeStop = nil
		return false, true
	default:
		state.ClaudeStop = nil
		return false, false
	}
}
