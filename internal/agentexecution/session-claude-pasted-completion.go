package agentexecution

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"time"
)

type claudeCompletionRecord struct {
	claudeInterruptedRecord
	SnakeSessionID        string             `json:"session_id"`
	PreventedContinuation *bool              `json:"preventedContinuation"`
	HookErrors            *[]json.RawMessage `json:"hookErrors"`
	FailedHooks           *[]json.RawMessage `json:"failedHookErrorIndexes"`
	AddedContext          *[]json.RawMessage `json:"hookAdditionalContext"`
}

func claudeCompletedEvidence(binding SessionBinding, turn, promptHash string, since int64) (*Result, string, map[string]int64) {
	path, info := claudeTranscriptPath(binding)
	if info == nil || turn == "" || promptHash == "" || since <= 0 {
		return nil, "", nil
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, "", nil
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return nil, "", nil
	}
	digest := sha256.New()
	decoder := json.NewDecoder(io.TeeReader(io.LimitReader(file, (64<<20)+1), digest))
	matched, terminal, compact := false, false, false
	reachable, pending, completed := map[string]bool{}, map[string]bool{}, map[string]int64{}
	finished := int64(0)
	finalText := ""
	for {
		var record claudeCompletionRecord
		if err := decoder.Decode(&record); err == io.EOF {
			break
		} else if err != nil || record.Sidechain {
			return nil, "", nil
		}
		normal := record.Type == "user" || record.Type == "assistant"
		var blocks []claudeInterruptedBlock
		content := bytes.TrimSpace(record.Message.Content)
		if normal && len(content) > 0 && content[0] == '[' {
			if json.Unmarshal(record.Message.Content, &blocks) != nil {
				return nil, "", nil
			}
		}
		// Earlier deferred work must not disappear behind the selected prompt or compaction.
		if record.Type == "assistant" {
			for _, block := range blocks {
				if block.Type == "tool_use" && !synchronousClaudeTool(block) {
					return nil, "", nil
				}
			}
		}
		text := claudeReportText(record.Message.Content)
		if !matched {
			if record.Type != "user" || record.Meta || record.Compact || record.PromptID != turn || claudeInputHash(text, promptHash) != promptHash {
				continue
			}
			stamp, err := time.Parse(time.RFC3339Nano, record.Timestamp)
			_, directoryOK := reportDirectory(binding.Directory, record.Cwd)
			if err != nil || stamp.UnixMilli() < since || record.SessionID != binding.ProviderID || record.UUID == "" || !filepath.IsAbs(record.Cwd) || !directoryOK {
				return nil, "", nil
			}
			matched, reachable[record.UUID] = true, true
			continue
		}
		if record.SessionID != "" && record.SessionID != binding.ProviderID {
			return nil, "", nil
		}
		if record.Cwd != "" {
			if _, ok := reportDirectory(binding.Directory, record.Cwd); !ok {
				return nil, "", nil
			}
		}
		if terminal {
			switch record.Type {
			case "cost-state", "ai-title", "last-prompt", "mode", "permission-mode", "atis-latch", "tools-used", "file-history-snapshot", "file-history-delta":
				continue
			}
			if record.Type == "system" && record.Subtype == "turn_duration" {
				continue
			}
			return nil, "", nil
		}
		linked := reachable[record.Parent] || reachable[record.LogicalParent]
		if record.UUID != "" && linked {
			if reachable[record.UUID] {
				return nil, "", nil
			}
			reachable[record.UUID] = true
		}
		if !normal {
			switch record.Type {
			case "system":
				if record.Subtype == "stop_hook_summary" {
					if !linked || finalText == "" || len(pending) != 0 || record.SnakeSessionID != binding.ProviderID || record.PreventedContinuation == nil || *record.PreventedContinuation || record.HookErrors == nil || len(*record.HookErrors) != 0 || record.FailedHooks == nil || len(*record.FailedHooks) != 0 || record.AddedContext == nil || len(*record.AddedContext) != 0 {
						return nil, "", nil
					}
					stamp, problem := time.Parse(time.RFC3339Nano, record.Timestamp)
					if problem != nil || stamp.UnixMilli() < since || stamp.After(time.Now().Add(time.Second)) {
						return nil, "", nil
					}
					terminal, finished = true, stamp.UnixMilli()
				}
				if record.Subtype == "compact_boundary" {
					if !linked || len(pending) != 0 || record.SessionID != binding.ProviderID || record.Cwd != binding.Directory {
						return nil, "", nil
					}
					compact = true
				}
			case "attachment", "last-prompt", "mode", "permission-mode", "atis-latch", "tools-used", "api-request-blob", "api-request", "api-request-shape", "file-history-snapshot", "file-history-delta", "cost-state", "ai-title":
			default:
				return nil, "", nil
			}
			continue
		}
		if !linked || record.UUID == "" || record.SessionID != binding.ProviderID || record.PromptID != "" && record.PromptID != turn {
			return nil, "", nil
		}
		stamp, err := time.Parse(time.RFC3339Nano, record.Timestamp)
		if err != nil {
			return nil, "", nil
		}
		if record.Type == "assistant" {
			if finalText != "" {
				return nil, "", nil
			}
			for _, block := range blocks {
				switch block.Type {
				case "text", "thinking", "redacted_thinking":
				case "tool_use":
					if block.ID == "" || pending[block.ID] || completed[block.ID] != 0 {
						return nil, "", nil
					}
					pending[block.ID] = true
				default:
					return nil, "", nil
				}
			}
			if record.Message.StopReason == "end_turn" && len(pending) == 0 && text != "" {
				finalText = text
			}
			continue
		}
		if record.PromptID != turn {
			return nil, "", nil
		}
		if record.Compact {
			if !compact || !record.VisibleOnly || len(pending) != 0 {
				return nil, "", nil
			}
			compact = false
			continue
		}

		if text != "" || len(blocks) == 0 {
			return nil, "", nil
		}
		for _, block := range blocks {
			if block.Type != "tool_result" || !pending[block.ToolUseID] || stamp.UnixMilli() > time.Now().Add(time.Second).UnixMilli() {
				return nil, "", nil
			}
			delete(pending, block.ToolUseID)
			completed[block.ToolUseID] = stamp.UnixMilli()
		}
	}
	after, err := file.Stat()
	if !matched || !terminal || err != nil || !os.SameFile(info, after) || after.Size() != info.Size() || !after.ModTime().Equal(info.ModTime()) {
		return nil, "", nil
	}
	for _, stamp := range completed {
		if stamp > finished {
			return nil, "", nil
		}
	}
	return &Result{State: "succeeded", Summary: finalText, ExitCode: 0, FinishedMS: finished}, hex.EncodeToString(digest.Sum(nil)), completed
}

func ownedClaudePastedTurn(binding SessionBinding, promptHash string, since int64) string {
	return ownedClaudePromptTurn(binding, promptHash, since, true)
}

func ownedClaudePromptTurn(binding SessionBinding, promptHash string, since int64, pastedOnly bool) string {
	path, info := claudeTranscriptPath(binding)
	if info == nil || info.Size() > 64<<20 {
		return ""
	}
	data, err := os.ReadFile(path)
	if err != nil || len(data) > 64<<20 {
		return ""
	}
	turn := ""
	for _, line := range bytes.Split(data, []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		var r claudeInterruptedRecord
		if json.Unmarshal(line, &r) != nil || r.Sidechain {
			return ""
		}
		text := claudeReportText(r.Message.Content)
		if r.Type != "user" || r.Meta || r.Compact || (pastedOnly && workspaceHash(text) == promptHash) || claudeInputHash(text, promptHash) != promptHash {
			continue
		}
		stamp, problem := time.Parse(time.RFC3339Nano, r.Timestamp)
		_, directoryOK := reportDirectory(binding.Directory, r.Cwd)
		if problem != nil || stamp.UnixMilli() < since || r.SessionID != binding.ProviderID || !filepath.IsAbs(r.Cwd) || !directoryOK || r.PromptID == "" || turn != "" {
			return ""
		}
		turn = r.PromptID
	}
	return turn
}

func (s Service) reconcileClaudePastedCompletion(ctx context.Context, key, dir, path string, spec Spec, receipt Receipt, state *sessionLifecycle) (Status, error) {
	empty := Status{}
	if spec.PreparedFrom == "" || spec.TimeoutSeconds <= 0 || receipt.Binding == nil || receipt.Workspace == nil || state.Executor != "claude" || state.State != "unknown" || state.UnknownReason != "SESSION_PROMPT_MISMATCH" || state.LaunchKey != key || state.ProviderConflict != nil || !reflect.DeepEqual(state.Binding, *receipt.Binding) || state.EndedIdle || len(state.Tools) != 0 {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	if err := s.preparedContinuation(spec, *state); err != nil {
		return empty, err
	}
	since := receipt.DeadlineMS - int64(spec.TimeoutSeconds)*1000
	hash := workspaceHash(sessionPrompt(dir, spec))
	turn := ownedClaudePastedTurn(state.Binding, hash, since)
	if turn == "" {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	return s.settleClaudeRecordedCompletion(ctx, key, dir, path, receipt, state, turn, hash, since)
}

func (s Service) settleClaudeRecordedCompletion(ctx context.Context, key, dir, path string, receipt Receipt, state *sessionLifecycle, turn, hash string, since int64) (Status, error) {
	return s.settleClaudeObservedOutcome(ctx, key, dir, path, receipt, state, turn, hash, func() (*Result, string, map[string]int64) {
		return claudeCompletedEvidence(state.Binding, turn, hash, since)
	})
}

func (s Service) settleClaudeObservedOutcome(ctx context.Context, key, dir, path string, receipt Receipt, state *sessionLifecycle, turn, hash string, observe func() (*Result, string, map[string]int64)) (Status, error) {
	empty := Status{}
	result, digest, completed := observe()
	for tool := range state.Tools {
		if completed[tool] == 0 {
			return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
		}
	}
	if result == nil || !sessionProcessesStopped(state.Binding) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
	}
	root, release, err := s.lockWorkspaceWriter(ctx, state.Binding.Directory)
	if err != nil {
		return empty, err
	}
	defer release()
	var writer struct {
		Key string `json:"key"`
	}
	if readJSON(filepath.Join(root, "writer.json"), &writer) != nil || writer.Key != key {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_WORKSPACE_CHANGED")
	}
	checked, again, confirmed := observe()
	for tool := range state.Tools {
		if confirmed[tool] == 0 {
			return empty, fmt.Errorf("SESSION_RECONCILIATION_EVIDENCE_CHANGED")
		}
	}
	if checked == nil || again != digest || !sessionProcessesStopped(state.Binding) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_EVIDENCE_CHANGED")
	}
	if err = ctx.Err(); err != nil {
		return empty, err
	}
	if _, err := os.Stat(filepath.Join(dir, "cancel.json")); err == nil {
		result.State = "cancelled"
	}
	yes := true
	result.InputStopped, result.OutcomeKnown, result.StopEvidence = &yes, &yes, digest
	if err = writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		return empty, err
	}
	state.State, state.UnknownReason, state.LaunchKey, state.CompletedKey = "idle", "", "", key
	state.TurnID, state.PromptHash, state.ClaudeStop = turn, hash, nil
	state.Tools = map[string]bool{}
	state.UpdatedMS = time.Now().UnixMilli()
	if err = writeJSON(path, *state); err != nil {
		return empty, err
	}
	receipt.State = result.State
	return Status{Receipt: receipt, Result: result}, nil
}
