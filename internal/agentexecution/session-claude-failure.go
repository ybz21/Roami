package agentexecution

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

type claudeFailureRecord struct {
	APIStatus int `json:"apiErrorStatus"`
	claudeReportRecord
	UUID       string `json:"uuid"`
	ParentUUID string `json:"parentUuid"`
	Timestamp  string `json:"timestamp"`
	Subtype    string `json:"subtype"`
	DurationMS *int64 `json:"durationMs"`
	APIError   bool   `json:"isApiErrorMessage"`
	NoToolCall bool   `json:"failedResponseHadNoToolCall"`
	Attachment struct {
		Type string `json:"type"`
	} `json:"attachment"`
	Message struct {
		Model      string          `json:"model"`
		Role       string          `json:"role"`
		Content    json.RawMessage `json:"content"`
		StopReason string          `json:"stop_reason"`
		Usage      *struct {
			Input  *int64 `json:"input_tokens"`
			Output *int64 `json:"output_tokens"`
		} `json:"usage"`
	} `json:"message"`
}

// A new provider must reject its first prompt before any agent tools can be ruled out.
func claudeRejectedResponse(binding SessionBinding, turn, promptHash string) (*Result, string) {
	return claudeRejectedWindow(binding, turn, promptHash, false)
}

// Explicit recovery can inspect a changed-input rejection window without accepting it as success.
func claudeExplicitRejectionEvidence(binding SessionBinding, turn, promptHash string) (*Result, string) {
	result, digest := claudeRejectedResponse(binding, turn, promptHash)
	if result == nil {
		return claudeRejectedWindow(binding, turn, promptHash, true)
	}
	return result, digest
}

var claudeModelCommand = regexp.MustCompile(`^<command-name>/model</command-name>\s*<command-message>model</command-message>\s*<command-args>[^<]*</command-args>$`)

func claudeRejectedWindow(binding SessionBinding, turn, promptHash string, changedInput bool) (*Result, string) {
	path, info := claudeTranscriptPath(binding)
	if info == nil || turn == "" || promptHash == "" {
		return nil, ""
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, ""
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return nil, ""
	}
	hash := sha256.New()
	decoder := json.NewDecoder(io.TeeReader(io.LimitReader(file, (64<<20)+1), hash))
	matched := false
	followups, commandStep := 0, 0
	commandPrompt, commandParent := "", ""
	seen := map[string]bool{turn: true}
	errorID := ""
	var errorTime, promptTime time.Time
	var result *Result
	for {
		var record claudeFailureRecord
		if err := decoder.Decode(&record); errors.Is(err, io.EOF) {
			break
		} else if err != nil {
			return nil, ""
		}
		if !matched {
			if record.Type != "user" || record.PromptID != turn {
				if record.Type == "user" || record.Type == "assistant" || record.Type == "system" || record.Sidechain {
					return nil, ""
				}
				continue
			}
			directory, ok := reportDirectory(binding.Directory, record.Cwd)
			if record.Sidechain || record.Meta || record.Compact || record.SessionID != binding.ProviderID || !ok || directory != binding.Directory || workspaceHash(claudeReportText(record.Message.Content)) != promptHash {
				return nil, ""
			}
			promptTime, err = time.Parse(time.RFC3339Nano, record.Timestamp)
			if err != nil || promptTime.After(time.Now().Add(5*time.Second)) {
				return nil, ""
			}
			matched = true
			continue
		}
		if record.Sidechain {
			return nil, ""
		}
		switch record.Type {
		case "user":
			if !changedInput || result == nil || record.Compact || record.UUID == "" {
				return nil, ""
			}
			directory, ok := reportDirectory(binding.Directory, record.Cwd)
			var text string
			stamp, stampErr := time.Parse(time.RFC3339Nano, record.Timestamp)
			if record.SessionID != binding.ProviderID || !ok || directory != binding.Directory || json.Unmarshal(record.Message.Content, &text) != nil || text == "" || stampErr != nil || stamp.UnixMilli() < result.FinishedMS || stamp.After(time.Now().Add(5*time.Second)) {
				return nil, ""
			}
			if commandStep != 0 {
				if record.PromptID != commandPrompt || record.ParentUUID != commandParent || record.Meta {
					return nil, ""
				}
				if commandStep == 1 && claudeModelCommand.MatchString(text) {
					commandStep = 2
				} else if commandStep == 2 && strings.HasPrefix(text, "<local-command-stdout>") && strings.HasSuffix(text, "</local-command-stdout>") {
					commandStep = 0
				} else {
					return nil, ""
				}
				commandParent = record.UUID
				continue
			}
			if record.PromptID == "" || seen[record.PromptID] {
				return nil, ""
			}
			seen[record.PromptID] = true
			followups++
			if record.Meta {
				if !strings.HasPrefix(text, "<local-command-caveat>") || !strings.HasSuffix(text, "</local-command-caveat>") {
					return nil, ""
				}
				commandStep, commandPrompt, commandParent = 1, record.PromptID, record.UUID
				continue
			}
			promptTime, errorID, result = stamp, "", nil
		case "assistant":
			if commandStep != 0 {
				return nil, ""
			}
			directory, ok := reportDirectory(binding.Directory, record.Cwd)
			usage := record.Message.Usage
			if record.APIStatus != 400 && record.APIStatus != 401 && record.APIStatus != 403 && record.APIStatus != 404 && record.APIStatus != 429 {
				return nil, ""
			}
			if errorID != "" || record.SessionID != binding.ProviderID || !ok || directory != binding.Directory || !record.APIError || !record.NoToolCall || record.Message.Model != "<synthetic>" || record.Message.Role != "assistant" || usage == nil || usage.Input == nil || usage.Output == nil || *usage.Input != 0 || *usage.Output != 0 || record.UUID == "" || (record.Message.StopReason != "stop_sequence" && record.Message.StopReason != "end_turn") {
				return nil, ""
			}
			var blocks []struct {
				Type string `json:"type"`
				Text string `json:"text"`
			}
			if json.Unmarshal(record.Message.Content, &blocks) != nil || len(blocks) == 0 {
				return nil, ""
			}
			for _, block := range blocks {
				if block.Type != "text" || block.Text == "" {
					return nil, ""
				}
			}
			errorTime, err = time.Parse(time.RFC3339Nano, record.Timestamp)
			if err != nil || errorTime.Before(promptTime) || errorTime.After(time.Now().Add(5*time.Second)) {
				return nil, ""
			}
			errorID = record.UUID
		case "system":
			stamp, err := time.Parse(time.RFC3339Nano, record.Timestamp)
			directory, ok := reportDirectory(binding.Directory, record.Cwd)
			if err != nil || result != nil || record.Subtype != "turn_duration" || errorID == "" || record.ParentUUID != errorID || record.SessionID != binding.ProviderID || !ok || directory != binding.Directory || stamp.Before(errorTime) || stamp.After(time.Now().Add(5*time.Second)) || record.DurationMS == nil || *record.DurationMS < 0 {
				return nil, ""
			}
			result = &Result{State: "failed", ErrorCode: "CLAUDE_API_REQUEST_FAILED", Summary: "CLAUDE_API_REQUEST_FAILED", ExitCode: -1, FinishedMS: stamp.UnixMilli()}
		case "attachment":
			if result != nil {
				return nil, ""
			}
			switch record.Attachment.Type {
			case "environment", "model", "deferred_tools_delta", "mcp_instructions_delta", "agent_listing_delta", "skill_listing", "instructions", "session_context", "date", "remote_session_change", "prompt_snapshot":
			default:
				return nil, ""
			}
		case "api-request-shape", "api-request-blob", "api-request":
			if result != nil || commandStep != 0 {
				return nil, ""
			}
		case "file-history-snapshot":
			if !changedInput {
				return nil, ""
			}
		case "last-prompt", "mode", "permission-mode", "atis-latch", "cost-state":
		default:
			return nil, ""
		}
	}
	after, err := file.Stat()
	current, pathErr := os.Lstat(path)
	if err != nil || pathErr != nil || !matched || result == nil || commandStep != 0 || (changedInput && followups == 0) || !os.SameFile(info, after) || !os.SameFile(info, current) || after.Size() != info.Size() || !after.ModTime().Equal(info.ModTime()) || current.Mode().Perm()&0022 != 0 {
		return nil, ""
	}
	return result, hex.EncodeToString(hash.Sum(nil))
}

func (s Service) reconcileClaudeRejection(key string, status Status, state *sessionLifecycle, statePath string) (Status, bool, error) {
	if state.Executor != "claude" || state.Structured || state.State != "unknown" || state.UnknownReason != "" || state.ProviderConflict != nil || state.LaunchKey != key || len(state.Tools) != 0 || state.Binding.ProviderID != status.Binding.ProviderID || state.Binding.resourceID() != status.Binding.resourceID() || state.Binding.PID != status.Binding.PID || state.Binding.Directory != status.Binding.Directory {
		return status, false, nil
	}
	dir, _ := s.directory(key)
	var spec Spec
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Executor != "claude" || workspaceHash(sessionPrompt(dir, spec)) != state.PromptHash {
		return status, false, nil
	}
	result, digest := claudeRejectedResponse(state.Binding, state.TurnID, state.PromptHash)
	if result == nil || !sessionProcessesStopped(state.Binding) {
		return status, false, nil
	}
	checked, digestAgain := claudeRejectedResponse(state.Binding, state.TurnID, state.PromptHash)
	if checked == nil || digestAgain != digest || !sessionProcessesStopped(state.Binding) {
		return status, false, nil
	}
	stopped := true
	result.InputStopped, result.OutcomeKnown, result.StopEvidence = &stopped, &stopped, digest
	if _, err := os.Stat(filepath.Join(dir, "cancel.json")); err == nil {
		result.State = "cancelled"
	}
	proof := completionSource{state.Binding.ProviderID, state.TurnID, digest, result.FinishedMS}
	proofPath := filepath.Join(dir, "completion-source.json")
	var prior completionSource
	if err := readJSON(proofPath, &prior); errors.Is(err, os.ErrNotExist) {
		if err := writeJSON(proofPath, proof); err != nil {
			return status, false, err
		}
	} else if err != nil {
		return status, false, err
	} else if prior != proof {
		return status, false, fmt.Errorf("SESSION_COMPLETION_EVIDENCE_CHANGED")
	}
	if err := writeJSON(filepath.Join(dir, "result.json"), result); err != nil {
		return status, false, err
	}
	state.State, state.LaunchKey, state.UnknownReason, state.CompletedKey = "idle", "", "", key
	state.UpdatedMS = time.Now().UnixMilli()
	if err := writeJSON(statePath, state); err != nil {
		return status, false, err
	}
	status.State, status.Result, status.ObservationErrorCode = result.State, result, ""
	return status, true, nil
}
