package agentexecution

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"strings"
)

// A human conversation may settle without a managed launch key.
func claudeNativeIdleEvidence(data []byte, state sessionLifecycle) bool {
	stop := state.ClaudeStop
	if state.Executor != "claude" || state.State != "idle" || state.LaunchKey != "" || state.CompletedKey != "" || state.UnknownReason != "" || state.ProviderConflict != nil || state.EndedIdle || len(state.Tools) != 0 || stop == nil || !stop.Idle || stop.PromptID == "" || stop.PromptID != state.TurnID || stop.PromptHash == "" || stop.PromptHash != state.PromptHash || stop.Summary == "" || len(data) == 0 || data[len(data)-1] != '\n' {
		return false
	}
	matched, final := false, false
	for _, line := range bytes.Split(data, []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		var r struct {
			claudeInterruptedRecord
			Message struct {
				Content    json.RawMessage `json:"content"`
				Model      string          `json:"model"`
				StopReason string          `json:"stop_reason"`
			} `json:"message"`
		}
		if json.Unmarshal(line, &r) != nil || r.Sidechain {
			return false
		}
		if !matched {
			if r.Type == "user" && !r.Meta && !r.Compact && r.PromptID == state.TurnID && claudeInputHash(claudeReportText(r.Message.Content), state.PromptHash) == state.PromptHash {
				if r.SessionID != state.Binding.ProviderID || r.Cwd != state.Binding.Directory {
					return false
				}
				matched = true
			}
			continue
		}
		if r.SessionID != "" && r.SessionID != state.Binding.ProviderID || r.Cwd != "" && r.Cwd != state.Binding.Directory {
			return false
		}
		switch r.Type {
		case "api-request", "api-request-blob", "api-request-shape":
			if final {
				return false
			}
		case "assistant":
			if final || strings.TrimPrefix(r.Message.Model, "roami-claude/") != strings.TrimPrefix(state.Model, "roami-claude/") {
				return false
			}
			if claudeReportText(r.Message.Content) == stop.Summary && r.Message.StopReason == "end_turn" {
				final = true
			}
		case "user":
			var blocks []claudeInterruptedBlock
			if final || json.Unmarshal(r.Message.Content, &blocks) != nil || len(blocks) == 0 {
				return false
			}
			for _, b := range blocks {
				if b.Type != "tool_result" {
					return false
				}
			}
		case "system":
			if r.Subtype != "stop_hook_summary" && r.Subtype != "turn_duration" {
				return false
			}
		case "attachment", "file-history-snapshot", "last-prompt", "ai-title", "mode", "permission-mode", "atis-latch", "cost-state":
		default:
			return false
		}
	}
	return matched && final
}

func provenClaudeNativeIdle(state sessionLifecycle) bool {
	path, info := claudeTranscriptPath(state.Binding)
	if info == nil {
		return false
	}
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	defer f.Close()
	opened, err := f.Stat()
	if err != nil || !os.SameFile(info, opened) || opened.Size() > 64<<20 {
		return false
	}
	data, err := io.ReadAll(io.LimitReader(f, (64<<20)+1))
	if err != nil || !claudeNativeIdleEvidence(data, state) {
		return false
	}
	latest, err := os.Stat(path)
	return err == nil && os.SameFile(opened, latest) && opened.Size() == latest.Size() && opened.ModTime() == latest.ModTime()
}
