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
	"strings"
	"time"
)

type claudeInterruptedRecord struct {
	claudeReportRecord
	UUID          string `json:"uuid"`
	Parent        string `json:"parentUuid"`
	LogicalParent string `json:"logicalParentUuid"`
	Timestamp     string `json:"timestamp"`
	Subtype       string `json:"subtype"`
	VisibleOnly   bool   `json:"isVisibleInTranscriptOnly"`
}

type claudeInterruptedBlock struct {
	Type      string         `json:"type"`
	ID        string         `json:"id"`
	Name      string         `json:"name"`
	ToolUseID string         `json:"tool_use_id"`
	Input     map[string]any `json:"input"`
}

func synchronousClaudeTool(block claudeInterruptedBlock) bool {
	if background, exists := block.Input["run_in_background"]; exists && background != false {
		return false
	}
	switch block.Name {
	case "Read", "Glob", "Grep", "ToolSearch", "Bash", "Write", "Edit":
		return true
	}
	return false
}

// Only an explicitly delivered interruption can turn missing hooks into a failed outcome.
func claudeInterruptedEvidence(binding SessionBinding, turn, promptHash string, since int64) (*Result, string, map[string]int64) {
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
	for {
		var record claudeInterruptedRecord
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
			if record.Type != "user" || record.Meta || record.Compact || record.PromptID != turn || workspaceHash(text) != promptHash {
				continue
			}
			stamp, err := time.Parse(time.RFC3339Nano, record.Timestamp)
			if err != nil || stamp.UnixMilli() > since || record.SessionID != binding.ProviderID || record.UUID == "" || record.Cwd != binding.Directory {
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
			case "cost-state", "last-prompt", "mode", "permission-mode", "atis-latch", "tools-used", "file-history-snapshot", "file-history-delta":
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
				if record.Subtype == "compact_boundary" {
					if !linked || len(pending) != 0 || record.SessionID != binding.ProviderID || record.Cwd != binding.Directory {
						return nil, "", nil
					}
					compact = true
				}
			case "attachment", "last-prompt", "mode", "permission-mode", "atis-latch", "tools-used", "api-request-blob", "api-request", "api-request-shape", "file-history-snapshot", "file-history-delta", "cost-state":
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
		if text == "[Request interrupted by user]" || text == "[Request interrupted by user for tool use]" {
			if record.Meta || len(pending) != 0 || stamp.UnixMilli() < since || stamp.After(time.Now().Add(time.Second)) {
				return nil, "", nil
			}
			terminal, finished = true, stamp.UnixMilli()
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
	return &Result{State: "failed", Summary: "SESSION_SCOPE_CHANGED_STOPPED", ErrorCode: "CLAUDE_SESSION_INTERRUPTED", ExitCode: -1, FinishedMS: finished}, hex.EncodeToString(digest.Sum(nil)), completed
}

func matchingClaudeInterrupt(dir string, binding SessionBinding, turn, promptHash string) (sessionInterrupt, bool) {
	var intent sessionInterrupt
	var cancel struct {
		Cancel bool `json:"cancel"`
	}
	if readJSON(filepath.Join(dir, "cancel.json"), &cancel) != nil || !cancel.Cancel {
		return intent, false
	}
	err := readJSON(filepath.Join(dir, "interrupt-request.json"), &intent)
	return intent, err == nil && intent.Delivered && (len(intent.Tools) == 0 || intent.ToolSignalsDelivered) && intent.CreatedMS > 0 && intent.ResourceID == binding.resourceID() && intent.ProviderID == binding.ProviderID && intent.TurnID == turn && intent.PromptHash == promptHash
}

func (s Service) reconcileClaudeInterrupted(ctx context.Context, key, dir, path string, spec Spec, receipt Receipt, binding SessionBinding, state *sessionLifecycle, previous Result, hasResult bool) (Status, error) {
	empty := Status{}
	intent, ok := matchingClaudeInterrupt(dir, state.Binding, state.TurnID, state.PromptHash)
	if !ok || state.Executor != "claude" || state.InitialLaunch || state.Structured || state.ProviderConflict != nil || state.LaunchKey != key || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) || state.Binding.ProviderID != receipt.Binding.ProviderID || state.Binding.resourceID() != binding.resourceID() || state.Binding.PID != binding.PID || state.Binding.Directory != binding.Directory || state.Binding.HostProof != sessionHostProof() || state.Binding.DirectoryProof != sessionDirectoryProof(binding.Directory) || state.Binding.ProviderHomeProof == "" || state.Binding.ProviderHomeProof != sessionDirectoryProof(state.Binding.ProviderHome) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	if state.State != "busy" && state.State != "unknown" {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	if state.State == "unknown" && state.UnknownReason != "" && state.UnknownReason != "SESSION_EVENT_INVALID_TURN" {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	observe := func() (*Result, string, map[string]int64) {
		return claudeInterruptedEvidence(state.Binding, state.TurnID, state.PromptHash, intent.CreatedMS)
	}
	result, evidence, completed := observe()
	if result == nil || !sessionProcessesStopped(state.Binding) {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
	}
	for tool := range state.Tools {
		if strings.HasPrefix(tool, "subagent:") || completed[tool] <= 0 {
			return empty, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
		}
	}
	if hasResult && previous.StopEvidence != evidence {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_EVIDENCE_CHANGED")
	}
	if receipt.Workspace == nil || receipt.Workspace.Directory != binding.Directory {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_WORKSPACE_REQUIRED")
	}
	root, release, err := s.lockWorkspaceWriter(ctx, binding.Directory)
	if err != nil {
		return empty, err
	}
	defer release()
	var writer struct {
		Key string `json:"key"`
	}
	if readJSON(filepath.Join(root, "writer.json"), &writer) != nil || !hasResult && writer.Key != key {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_WORKSPACE_CHANGED")
	}
	checked, latest, _ := observe()
	current, currentErr := s.paneBinding(binding.Name, false)
	if checked == nil || latest != evidence || !sessionProcessesStopped(state.Binding) || currentErr != nil || current.resourceID() != binding.resourceID() || current.PID != binding.PID || current.Directory != binding.Directory {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_EVIDENCE_CHANGED")
	}
	if err := ctx.Err(); err != nil {
		return empty, err
	}
	audit := struct {
		Original  sessionLifecycle `json:"originalLifecycle"`
		Evidence  string           `json:"transcriptSha256"`
		Completed map[string]int64 `json:"completedTools"`
	}{*state, evidence, completed}
	if err := writeJSON(filepath.Join(dir, "claude-interruption-reconciliation.json"), audit); err != nil {
		return empty, err
	}
	stopped := true
	result.InputStopped, result.OutcomeKnown, result.StopEvidence = &stopped, &stopped, evidence
	if err := writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		return empty, err
	}
	state.State, state.UnknownReason, state.LaunchKey = "idle", "", ""
	state.CompletedKey, state.Tools, state.ClaudeStop = key, map[string]bool{}, nil
	state.UpdatedMS = time.Now().UnixMilli()
	if err := writeJSON(path, state); err != nil {
		return empty, err
	}
	receipt.State = "failed"
	return Status{Receipt: receipt, Result: result}, nil
}
