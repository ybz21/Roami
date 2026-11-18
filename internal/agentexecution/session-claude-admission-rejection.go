package agentexecution

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"time"
)

// A typed gateway refusal before generation needs no fabricated Stop hook.
func claudeAdmissionRejectedEvidence(binding SessionBinding, turn, hash string, since int64) (*Result, string, map[string]int64) {
	path, info := claudeTranscriptPath(binding)
	if info == nil || info.Size() > 64<<20 || info.Mode().Perm()&0022 != 0 || turn == "" || hash == "" || since <= 0 {
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
	root := ""
	var promptTime time.Time
	var result *Result
	for {
		var r claudeFailureRecord
		if err := decoder.Decode(&r); err == io.EOF {
			break
		} else if err != nil || r.Sidechain {
			return nil, "", nil
		}
		if root == "" {
			if r.Type != "user" || r.PromptID != turn {
				continue
			}
			_, owned := reportDirectory(binding.Directory, r.Cwd)
			stamp, problem := time.Parse(time.RFC3339Nano, r.Timestamp)
			if r.Meta || r.Compact || r.UUID == "" || r.SessionID != binding.ProviderID || !filepath.IsAbs(r.Cwd) || !owned || claudeInputHash(claudeReportText(r.Message.Content), hash) != hash || problem != nil || stamp.UnixMilli() < since || stamp.After(time.Now().Add(time.Second)) {
				return nil, "", nil
			}
			root, promptTime = r.UUID, stamp
			continue
		}
		if r.SessionID != "" && r.SessionID != binding.ProviderID {
			return nil, "", nil
		}
		if r.Cwd != "" {
			if _, owned := reportDirectory(binding.Directory, r.Cwd); !filepath.IsAbs(r.Cwd) || !owned {
				return nil, "", nil
			}
		}
		switch r.Type {
		case "assistant":
			usage := r.Message.Usage
			if result != nil || r.ParentUUID != root || r.UUID == "" || r.SessionID != binding.ProviderID || r.APIStatus != 402 || !r.APIError || !r.NoToolCall || r.Message.Model != "<synthetic>" || r.Message.Role != "assistant" || r.Message.StopReason != "stop_sequence" || usage == nil || usage.Input == nil || usage.Output == nil || *usage.Input != 0 || *usage.Output != 0 {
				return nil, "", nil
			}
			var blocks []struct {
				Type string `json:"type"`
				Text string `json:"text"`
			}
			if json.Unmarshal(r.Message.Content, &blocks) != nil || len(blocks) != 1 || blocks[0].Type != "text" {
				return nil, "", nil
			}
			body, ok := strings.CutPrefix(blocks[0].Text, "API Error: 402 ")
			if !ok {
				return nil, "", nil
			}
			var rejection struct {
				Error struct {
					Code string `json:"code"`
				} `json:"error"`
			}
			if json.Unmarshal([]byte(body), &rejection) != nil || rejection.Error.Code != "MODEL_PROXY_DAILY_LIMIT" {
				return nil, "", nil
			}
			stamp, problem := time.Parse(time.RFC3339Nano, r.Timestamp)
			if problem != nil || stamp.Before(promptTime) || stamp.After(time.Now().Add(time.Second)) {
				return nil, "", nil
			}
			result = &Result{State: "failed", ErrorCode: rejection.Error.Code, Summary: rejection.Error.Code, ExitCode: -1, FinishedMS: stamp.UnixMilli()}
		case "api-request", "api-request-blob", "api-request-shape", "file-history-snapshot":
			if result != nil {
				return nil, "", nil
			}
		case "last-prompt", "mode", "permission-mode", "atis-latch", "cost-state", "ai-title":
		default:
			return nil, "", nil
		}
	}
	after, err := file.Stat()
	current, problem := os.Lstat(path)
	if root == "" || result == nil || err != nil || problem != nil || !os.SameFile(info, after) || !os.SameFile(info, current) || after.Size() != info.Size() || !after.ModTime().Equal(info.ModTime()) || current.Mode().Perm()&0022 != 0 {
		return nil, "", nil
	}
	return result, hex.EncodeToString(digest.Sum(nil)), map[string]int64{}
}

func (s Service) reconcileClaudeAdmissionRejection(ctx context.Context, key, dir, path string, spec Spec, receipt Receipt, state *sessionLifecycle) (Status, bool, error) {
	if !spec.Persistent || spec.SessionID == "" || spec.TimeoutSeconds < 0 || receipt.Binding == nil || receipt.Workspace == nil || state.Executor != "claude" || state.Structured || state.State != "unknown" || state.UnknownReason != "" || state.LaunchKey != key || state.ProviderConflict != nil || state.EndedIdle || len(state.Tools) != 0 || state.TurnID == "" || !reflect.DeepEqual(state.Binding, *receipt.Binding) || receipt.Workspace.Directory != state.Binding.Directory || state.PromptHash != workspaceHash(sessionPrompt(dir, spec)) {
		return Status{}, false, nil
	}
	if spec.PreparedFrom != "" {
		if err := s.preparedContinuation(spec, *state); err != nil {
			return Status{}, false, nil
		}
	}
	info, err := os.Stat(filepath.Join(dir, "spec.json"))
	if err != nil {
		return Status{}, false, err
	}
	observe := func() (*Result, string, map[string]int64) {
		return claudeAdmissionRejectedEvidence(state.Binding, state.TurnID, state.PromptHash, info.ModTime().UnixMilli())
	}
	if result, _, _ := observe(); result == nil {
		return Status{}, false, nil
	}
	result, err := s.settleClaudeObservedOutcome(ctx, key, dir, path, receipt, state, state.TurnID, state.PromptHash, observe)
	return result, true, err
}
