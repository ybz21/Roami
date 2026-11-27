package agentexecution

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
)

// Auto-mode rejection can produce a tool result without its terminal tool hook.
func (s Service) reconcileClaudeToolCompletion(ctx context.Context, key, dir, path string, spec Spec, receipt Receipt, state *sessionLifecycle) (Status, error) {
	if spec.SessionID == "" || spec.TimeoutSeconds < 0 || receipt.Binding == nil || receipt.Workspace == nil || state.Executor != "claude" || state.Structured || state.State != "unknown" || state.UnknownReason != "" || state.LaunchKey != key || state.ProviderConflict != nil || state.EndedIdle || len(state.Tools) == 0 || state.TurnID == "" || !reflect.DeepEqual(state.Binding, *receipt.Binding) || receipt.Workspace.Directory != state.Binding.Directory || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return Status{}, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	since, err := storedClaudeSubmissionTime(dir, spec, receipt)
	if err != nil {
		return Status{}, err
	}
	return s.settleClaudeRecordedCompletion(ctx, key, dir, path, receipt, state, state.TurnID, state.PromptHash, since)
}

func storedClaudeSubmissionTime(dir string, spec Spec, receipt Receipt) (int64, error) {
	if spec.TimeoutSeconds > 0 {
		since := receipt.DeadlineMS - int64(spec.TimeoutSeconds)*1000
		if since > 0 {
			return since, nil
		}
	} else if spec.TimeoutSeconds == 0 && receipt.DeadlineMS == 0 {
		info, err := os.Stat(filepath.Join(dir, "spec.json"))
		if err != nil {
			return 0, err
		}
		return info.ModTime().UnixMilli(), nil
	}
	return 0, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
}
