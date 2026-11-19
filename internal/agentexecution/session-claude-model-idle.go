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
	"regexp"
	"strings"
	"time"
)

// A local model picker has its own prompt ID but does not execute another user turn.
func claudeSameModelSuffix(data []byte, binding SessionBinding, turn, promptHash, summary, model string, finished int64) bool {
	if len(data) == 0 || data[len(data)-1] != '\n' || turn == "" || model == "" || summary == "" || finished <= 0 {
		return false
	}
	command := regexp.MustCompile(`^<command-name>/model</command-name>\n[ \t]*<command-message>model</command-message>\n[ \t]*<command-args>(?:` + regexp.QuoteMeta(model) + `)?</command-args>$`)
	matched, terminal, count, phase := false, false, 0, 0
	localPrompt := ""
	for _, line := range bytes.Split(data, []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		var r claudeInterruptedRecord
		if json.Unmarshal(line, &r) != nil || r.Sidechain {
			return false
		}
		if r.SessionID != "" && r.SessionID != binding.ProviderID || r.Cwd != "" && r.Cwd != binding.Directory {
			return false
		}
		if !matched {
			if r.Type == "user" && !r.Meta && !r.Compact && r.PromptID == turn && claudeInputHash(claudeReportText(r.Message.Content), promptHash) == promptHash {
				matched = true
			}
			continue
		}
		if !terminal {
			if r.Type == "user" && !r.Meta && !r.Compact && r.PromptID != turn {
				return false
			}
			if r.Type == "assistant" && claudeReportText(r.Message.Content) == summary {
				stamp, err := time.Parse(time.RFC3339Nano, r.Timestamp)
				if err != nil || stamp.UnixMilli() > finished {
					return false
				}
				terminal = true
			}
			continue
		}
		switch r.Type {
		case "file-history-snapshot", "last-prompt", "mode", "permission-mode", "atis-latch", "cost-state", "ai-title":
		case "attachment":
			if count != 0 || phase != 0 || (r.Attachment.Type != "prompt_snapshot" && r.Attachment.Type != "hook_success") {
				return false
			}
		case "system":
			if r.Subtype != "stop_hook_summary" && r.Subtype != "turn_duration" {
				return false
			}
		case "user":
			if r.SessionID != binding.ProviderID || r.Cwd != binding.Directory || r.PromptID == "" || r.PromptID == turn {
				return false
			}
			var text string
			if json.Unmarshal(r.Message.Content, &text) != nil {
				return false
			}
			switch phase {
			case 0:
				if !r.Meta || text != claudeLocalCommandCaveat {
					return false
				}
				localPrompt = r.PromptID
				phase = 1
			case 1:
				if r.Meta || r.PromptID != localPrompt || !command.MatchString(text) {
					return false
				}
				phase = 2
			case 2:
				if r.Meta || r.PromptID != localPrompt || !strings.HasPrefix(text, "<local-command-stdout>Set model to `"+model+"`") || !strings.HasSuffix(text, "</local-command-stdout>") {
					return false
				}
				phase = 0
				count++
			}
		default:
			return false
		}
	}
	return matched && terminal && count > 0 && phase == 0
}

func (s Service) provenClaudeModelIdle(state sessionLifecycle) (sessionLifecycle, string, bool) {
	if state.Executor != "claude" || state.State != "unknown" || state.UnknownReason != "" || state.LaunchKey != "" || state.CompletedKey == "" || state.EndedIdle || state.ProviderConflict != nil || len(state.Tools) != 0 {
		return state, "", false
	}
	dir, err := s.directory(state.CompletedKey)
	if err != nil {
		return state, "", false
	}
	var spec Spec
	var receipt Receipt
	var result Result
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Key != state.CompletedKey || spec.Executor != "claude" || readJSON(filepath.Join(dir, "receipt.json"), &receipt) != nil || receipt.Binding == nil || !reflect.DeepEqual(*receipt.Binding, state.Binding) || readJSON(filepath.Join(dir, "result.json"), &result) != nil || result.State != "succeeded" || result.InputStopped == nil || !*result.InputStopped || result.OutcomeKnown == nil || !*result.OutcomeKnown || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return state, "", false
	}
	path, info := claudeTranscriptPath(state.Binding)
	if info == nil || info.Size() > 64<<20 {
		return state, "", false
	}
	file, err := os.Open(path)
	if err != nil {
		return state, "", false
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(opened, info) {
		return state, "", false
	}
	data, err := io.ReadAll(io.LimitReader(file, (64<<20)+1))
	if err != nil || len(data) > 64<<20 || !claudeSameModelSuffix(data, state.Binding, state.TurnID, state.PromptHash, result.Summary, state.Model, result.FinishedMS) {
		return state, "", false
	}
	after, err := os.Stat(path)
	if err != nil || !os.SameFile(opened, after) || opened.Size() != after.Size() || !opened.ModTime().Equal(after.ModTime()) || int64(len(data)) != after.Size() || !sessionProcessesStopped(state.Binding) {
		return state, "", false
	}
	digest := sha256.Sum256(data)
	state.State = "idle"
	return state, hex.EncodeToString(digest[:]), true
}

func (s Service) reconcileClaudeModelIdle(ctx context.Context, key string, receipt Receipt, result Result) (Status, error) {
	if receipt.Binding == nil {
		return Status{}, fmt.Errorf("SESSION_RECONCILIATION_BINDING_REQUIRED")
	}
	actual, err := s.paneBinding(receipt.Session, false)
	if err != nil || actual.resourceID() != receipt.Binding.resourceID() || actual.PID != receipt.Binding.PID || actual.Directory != receipt.Binding.Directory {
		return Status{}, fmt.Errorf("SESSION_RECONCILIATION_BINDING_CHANGED")
	}
	path, err := s.lifecycleFile(actual)
	if err != nil {
		return Status{}, err
	}
	unlock, err := lock(filepath.Join(filepath.Dir(path), "state.lock"))
	if err != nil {
		return Status{}, err
	}
	defer unlock()
	var state sessionLifecycle
	if readJSON(path, &state) != nil {
		return Status{}, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	if state.CompletedKey == "" {
		dir, _ := s.directory(key)
		var initial Spec
		current := Spec{Executor: "claude", SessionID: actual.ID, PreparedFrom: key}
		if readJSON(filepath.Join(dir, "spec.json"), &initial) != nil || !preparedOriginMatches(current, state, initial, receipt, result) {
			return Status{}, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
		}
		reconciled, problem := reconcileDirectClaudeCompletion(ctx, actual, &state, path)
		if problem != nil {
			return Status{}, problem
		}
		if !reconciled && !confirmedDirectClaudeIdle(actual, state, path) {
			return Status{}, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
		}
		receipt.State = result.State
		return Status{Receipt: receipt, Result: &result}, nil
	}
	if state.CompletedKey != key {
		return Status{}, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	if state.State == "idle" && state.LaunchKey == "" && reflect.DeepEqual(state.Binding, *receipt.Binding) {
		receipt.State = result.State
		return Status{Receipt: receipt, Result: &result}, nil
	}
	next, digest, ok := s.provenClaudeModelIdle(state)
	if !ok {
		return Status{}, fmt.Errorf("SESSION_RECONCILIATION_STOP_UNCONFIRMED")
	}
	if err = ctx.Err(); err != nil {
		return Status{}, err
	}
	dir, _ := s.directory(key)
	if err = writeJSON(filepath.Join(dir, "model-idle-reconciliation.json"), map[string]any{"key": key, "providerId": state.Binding.ProviderID, "model": state.Model, "sourceSha256": digest, "checkedMs": time.Now().UnixMilli()}); err != nil {
		return Status{}, err
	}
	next.UpdatedMS = time.Now().UnixMilli()
	if err = writeJSON(path, next); err != nil {
		return Status{}, err
	}
	receipt.State = result.State
	return Status{Receipt: receipt, Result: &result}, nil
}
