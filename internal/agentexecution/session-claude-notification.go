package agentexecution

import (
	"encoding/json"
	"io"
	"os"
)

// Claude also submits background task notices through UserPromptSubmit.
func claudeTaskNotification(state sessionLifecycle, event SessionEvent) bool {
	if state.Executor != "claude" || state.State != "busy" || state.LaunchKey == "" || state.ProviderConflict != nil || state.TurnID == "" || state.PromptHash == "" || event.ProviderID != state.Binding.ProviderID || event.TurnID != state.TurnID || event.Prompt == "" || workspaceHash(event.Prompt) == state.PromptHash {
		return false
	}
	path, info := claudeTranscriptPath(state.Binding)
	if info == nil {
		return false
	}
	file, err := os.Open(path)
	if err != nil {
		return false
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return false
	}
	decoder := json.NewDecoder(io.LimitReader(file, (64<<20)+1))
	matched, notification := false, false
	for {
		var record struct {
			claudeReportRecord
			Attachment struct {
				Type        string `json:"type"`
				Prompt      string `json:"prompt"`
				CommandMode string `json:"commandMode"`
				Origin      struct {
					Kind     string `json:"kind"`
					Producer string `json:"producer"`
					Subkind  string `json:"subkind"`
				} `json:"origin"`
			} `json:"attachment"`
		}
		if err = decoder.Decode(&record); err == io.EOF {
			break
		} else if err != nil {
			return false
		}
		if record.Sidechain {
			return false
		}
		if record.Type == "user" || record.Type == "assistant" {
			if record.SessionID != state.Binding.ProviderID {
				return false
			}
			text := claudeReportText(record.Message.Content)
			if record.Type == "user" && text != "" {
				if !matched && record.PromptID != state.TurnID {
					continue
				}
				if matched || record.Meta || record.Compact || workspaceHash(text) != state.PromptHash || record.Cwd != state.Binding.Directory {
					return false
				}
				matched = true
			}
		}
		attachment := record.Attachment
		if matched && record.Type == "attachment" && attachment.Type == "queued_command" {
			if record.SessionID != state.Binding.ProviderID || record.Cwd != state.Binding.Directory || attachment.CommandMode != "task-notification" || attachment.Origin.Kind != "task-notification" || attachment.Origin.Producer != "session-task" || attachment.Origin.Subkind != "" {
				return false
			}
			notification = notification || attachment.Prompt == event.Prompt
		}
	}
	after, err := file.Stat()
	current, pathErr := os.Lstat(path)
	return notification && err == nil && pathErr == nil && os.SameFile(info, after) && os.SameFile(info, current) && after.Size() == info.Size() && after.ModTime().Equal(info.ModTime()) && current.Mode().Perm()&0022 == 0
}
