package agentexecution

import (
	"bytes"
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
	"syscall"
	"time"
)

var codexThreadID = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

type codexRecord struct {
	Type      string          `json:"type"`
	Timestamp string          `json:"timestamp"`
	Payload   json.RawMessage `json:"payload"`
}

type codexPayload struct {
	Type          string `json:"type"`
	ID            string `json:"id"`
	Cwd           string `json:"cwd"`
	TurnID        string `json:"turn_id"`
	RootTurnID    string `json:"root_turn_id"`
	LastAssistant string `json:"last_agent_message"`
	CallID        string `json:"call_id"`
	Role          string `json:"role"`
	Phase         string `json:"phase"`
	Status        string `json:"status"`
	Content       []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	} `json:"content"`
}

// A stable provider transcript can reconcile a lost callback, without replaying input.
func codexCompletion(binding SessionBinding, turn, promptHash string) (*Result, string) {
	if !codexThreadID.MatchString(binding.ProviderID) || turn == "" || promptHash == "" {
		return nil, ""
	}
	home := os.Getenv("CODEX_HOME")
	if home == "" {
		userHome, err := os.UserHomeDir()
		if err != nil {
			return nil, ""
		}
		home = filepath.Join(userHome, ".codex")
	}
	root, err := filepath.EvalSymlinks(filepath.Join(home, "sessions"))
	if err != nil {
		return nil, ""
	}
	paths, err := filepath.Glob(filepath.Join(root, "*", "*", "*", "rollout-*-"+binding.ProviderID+".jsonl"))
	if err != nil || len(paths) != 1 {
		return nil, ""
	}
	path := paths[0]
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return nil, ""
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0002 != 0 || info.Size() > 64<<20 {
		return nil, ""
	}
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !ok || owner.Uid != uint32(os.Geteuid()) {
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
	// Active histories normally end in tool or token records; avoid scanning them repeatedly.
	tail := make([]byte, min(info.Size(), 256<<10))
	if _, err = file.ReadAt(tail, info.Size()-int64(len(tail))); err != nil {
		return nil, ""
	}
	tail = bytes.TrimSpace(tail)
	line := tail[bytes.LastIndexByte(tail, '\n')+1:]
	var last codexRecord
	var end codexPayload
	if json.Unmarshal(line, &last) != nil || last.Type != "event_msg" || json.Unmarshal(last.Payload, &end) != nil || end.Type != "task_complete" || end.TurnID != turn {
		return nil, ""
	}
	if _, err = file.Seek(0, io.SeekStart); err != nil {
		return nil, ""
	}
	hash := sha256.New()
	decoder := json.NewDecoder(io.TeeReader(io.LimitReader(file, (64<<20)+1), hash))
	active, assistant := "", ""
	metadata, matched, finalAnswer, aborted := false, false, false, false
	calls := map[string]bool{}
	var result *Result
	for {
		var record codexRecord
		if err = decoder.Decode(&record); errors.Is(err, io.EOF) {
			break
		} else if err != nil {
			return nil, ""
		}
		var value codexPayload
		if json.Unmarshal(record.Payload, &value) != nil {
			return nil, ""
		}
		switch record.Type {
		case "session_meta":
			directory, e := canonicalWorkspace(value.Cwd)
			if e != nil || directory != binding.Directory || value.ID != binding.ProviderID {
				return nil, ""
			}
			metadata = true
		case "event_msg":
			if value.Type == "task_started" {
				active, assistant, matched, result = value.TurnID, "", false, nil
				finalAnswer, aborted = false, false
				calls = map[string]bool{}
			} else if active == turn && (value.Type == "turn_aborted" || value.Type == "task_failed") {
				aborted = true
			} else if value.Type == "task_complete" {
				if active != turn {
					continue
				}
				stamp, e := time.Parse(time.RFC3339Nano, record.Timestamp)
				if e != nil || active != turn || value.TurnID != turn || (value.RootTurnID != "" && value.RootTurnID != turn) || !matched || len(calls) != 0 || !finalAnswer || aborted || assistant == "" || assistant != value.LastAssistant {
					return nil, ""
				}
				result = &Result{State: "succeeded", Summary: truncate(assistant, 32000), FinishedMS: stamp.UnixMilli()}
			}
		case "response_item":
			if active != turn {
				continue
			}
			switch value.Type {
			case "message":
				text := ""
				for _, part := range value.Content {
					if part.Type == "input_text" || part.Type == "output_text" || part.Type == "text" {
						text += part.Text
					}
				}
				if value.Role == "user" {
					if matched {
						return nil, ""
					}
					matched = workspaceHash(text) == promptHash
				} else if value.Role == "assistant" {
					assistant = text
					finalAnswer = value.Phase == "final_answer"
				}
			case "function_call", "custom_tool_call":
				if value.CallID == "" || calls[value.CallID] {
					return nil, ""
				}
				calls[value.CallID] = true
			case "function_call_output", "custom_tool_call_output":
				if !calls[value.CallID] {
					return nil, ""
				}
				delete(calls, value.CallID)
			default:
				if strings.HasSuffix(value.Type, "_call") && value.Status != "completed" {
					return nil, ""
				}
			}
		}
	}
	after, err := file.Stat()
	if err != nil || !metadata || result == nil || after.Size() != info.Size() || !after.ModTime().Equal(info.ModTime()) {
		return nil, ""
	}
	current, err := os.Lstat(path)
	if err != nil || !os.SameFile(info, current) || current.Mode().Perm()&0002 != 0 {
		return nil, ""
	}
	return result, hex.EncodeToString(hash.Sum(nil))
}

func (s Service) reconcileCodexCompletion(key string, status Status, state *sessionLifecycle, path string) (Status, bool, error) {
	if state.Executor != "codex" || (state.State != "unknown" && state.State != "busy") || state.LaunchKey != key || state.Binding.ProviderID != status.Binding.ProviderID || len(state.Tools) != 0 {
		return status, false, nil
	}
	dir, _ := s.directory(key)
	var spec Spec
	if readJSON(filepath.Join(dir, "spec.json"), &spec) != nil || spec.Executor != "codex" || workspaceHash(sessionPrompt(dir, spec)) != state.PromptHash {
		return status, false, nil
	}
	result, evidence := codexCompletion(*status.Binding, state.TurnID, state.PromptHash)
	if result == nil || !sessionProcessesStopped(*status.Binding) {
		return status, false, nil
	}
	stopped := true
	result.InputStopped, result.OutcomeKnown = &stopped, &stopped
	if _, err := os.Stat(filepath.Join(dir, "cancel.json")); err == nil {
		result.State, result.Summary = "cancelled", "Session task stopped after cancellation request"
	}
	proof := completionSource{state.Binding.ProviderID, state.TurnID, evidence, result.FinishedMS}
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
	state.State, state.LaunchKey, state.Tools = "idle", "", map[string]bool{}
	state.UpdatedMS = time.Now().UnixMilli()
	if err := writeJSON(path, state); err != nil {
		return status, false, err
	}
	status.State, status.Result = result.State, result
	return status, true, nil
}

type completionSource struct {
	ProviderID       string `json:"providerConversationId"`
	TurnID           string `json:"turnId"`
	TranscriptSHA256 string `json:"transcriptSha256"`
	FinishedMS       int64  `json:"finishedMs"`
}
