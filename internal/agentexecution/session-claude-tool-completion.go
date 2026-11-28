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
	return s.settleClaudeObservedOutcome(ctx, key, dir, path, receipt, state, state.TurnID, state.PromptHash, func() (*Result, string, map[string]int64) {
		return claudeTerminalEvidence(state.Binding, state.TurnID, state.PromptHash, since, "", true)
	})
}

func claudeFinalGatewayRefusal(record claudeCompletionRecord, blocks []claudeInterruptedBlock, text string) string {
	usage := record.Message.Usage
	if record.APIStatus != 503 || !record.NoToolCall || record.Meta || record.Compact || record.Message.Role != "assistant" || record.Message.Model != "<synthetic>" || record.Message.StopReason != "stop_sequence" || usage == nil || usage.Input == nil || usage.Output == nil || *usage.Input != 0 || *usage.Output != 0 || len(blocks) != 1 || blocks[0].Type != "text" {
		return ""
	}
	return claudeGatewayAdmissionCode(claudeFailureRecord{APIStatus: record.APIStatus, Failure: record.APIFailure}, text)
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
