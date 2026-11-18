package agentexecution

import (
	"context"
	"fmt"
	"reflect"
)

// Auto-mode rejection can produce a tool result without its terminal tool hook.
func (s Service) reconcileClaudeToolCompletion(ctx context.Context, key, dir, path string, spec Spec, receipt Receipt, state *sessionLifecycle) (Status, error) {
	if spec.SessionID == "" || spec.TimeoutSeconds <= 0 || receipt.Binding == nil || receipt.Workspace == nil || state.Executor != "claude" || state.Structured || state.State != "unknown" || state.UnknownReason != "" || state.LaunchKey != key || state.ProviderConflict != nil || state.EndedIdle || len(state.Tools) == 0 || state.TurnID == "" || !reflect.DeepEqual(state.Binding, *receipt.Binding) || receipt.Workspace.Directory != state.Binding.Directory || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return Status{}, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	since := receipt.DeadlineMS - int64(spec.TimeoutSeconds)*1000
	return s.settleClaudeRecordedCompletion(ctx, key, dir, path, receipt, state, state.TurnID, state.PromptHash, since)
}
