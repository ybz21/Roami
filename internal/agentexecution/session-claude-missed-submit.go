package agentexecution

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"time"
)

func claudeRejectedSubmit(binding SessionBinding, turn, hash string, since int64) bool {
	path, info := claudeTranscriptPath(binding)
	if info == nil || info.Size() > 64<<20 {
		return false
	}
	data, err := os.ReadFile(path)
	if err != nil || len(data) > 64<<20 {
		return false
	}
	root := ""
	for _, line := range bytes.Split(data, []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		var record struct {
			claudeInterruptedRecord
			Attachment struct {
				Type     string `json:"type"`
				HookName string `json:"hookName"`
				Event    string `json:"hookEvent"`
				Stderr   string `json:"stderr"`
				ExitCode int    `json:"exitCode"`
			} `json:"attachment"`
		}
		if json.Unmarshal(line, &record) != nil || record.Sidechain {
			return false
		}
		if record.Type == "user" && record.PromptID == turn && !record.Meta && !record.Compact && claudeInputHash(claudeReportText(record.Message.Content), hash) == hash {
			root = record.UUID
		}
		failure := record.Attachment
		if root == "" || record.Type != "attachment" || record.Parent != root || record.SessionID != binding.ProviderID || record.Cwd != binding.Directory || failure.Type != "hook_non_blocking_error" || failure.HookName != "UserPromptSubmit" || failure.Event != "UserPromptSubmit" || failure.ExitCode != 1 || !strings.HasSuffix(failure.Stderr, "INVALID_SESSION_EVENT") {
			continue
		}
		stamp, err := time.Parse(time.RFC3339Nano, record.Timestamp)
		return err == nil && stamp.UnixMilli() >= since && !stamp.After(time.Now().Add(time.Second))
	}
	return false
}

// A rejected start hook needs the original complete input and terminal transcript, not a replay.
func (s Service) reconcileClaudeMissedSubmit(ctx context.Context, key, dir, path string, spec Spec, receipt Receipt, state *sessionLifecycle) (Status, error) {
	empty := Status{}
	if spec.PreparedFrom == "" || spec.SessionID == "" || len(spec.Prompt) <= 100000 || receipt.Binding == nil || receipt.Workspace == nil || state.Executor != "claude" || state.Structured || state.State != "unknown" || state.UnknownReason != "SESSION_TOOL_EVENT_MISMATCH" || state.LaunchKey != key || state.ProviderConflict != nil || state.EndedIdle || !reflect.DeepEqual(state.Binding, *receipt.Binding) || receipt.Workspace.Directory != state.Binding.Directory {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	if err := s.preparedContinuation(spec, *state); err != nil {
		return empty, err
	}
	info, err := os.Stat(filepath.Join(dir, "spec.json"))
	if err != nil {
		return empty, err
	}
	since := info.ModTime().UnixMilli()
	hash := workspaceHash(sessionPrompt(dir, spec))
	turn := ownedClaudePromptTurn(state.Binding, hash, since, false)
	if turn == "" || !claudeRejectedSubmit(state.Binding, turn, hash, since) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	return s.settleClaudeRecordedCompletion(ctx, key, dir, path, receipt, state, turn, hash, since)
}
