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
	"strconv"
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
	result := readClaudeAdmissionRejection(binding, turn, hash, since, io.TeeReader(io.LimitReader(file, (64<<20)+1), digest))
	after, err := file.Stat()
	current, problem := os.Lstat(path)
	if result == nil || err != nil || problem != nil || !sameClaudeInputFile(info, after) || !sameClaudeInputFile(info, current) {
		return nil, "", nil
	}
	return result, hex.EncodeToString(digest.Sum(nil)), map[string]int64{}
}

func readClaudeAdmissionRejection(binding SessionBinding, turn, hash string, since int64, input io.Reader) *Result {
	decoder := json.NewDecoder(input)
	root := ""
	var promptTime time.Time
	parent := ""
	var result *Result
	for {
		var r claudeFailureRecord
		if err := decoder.Decode(&r); err == io.EOF {
			break
		} else if err != nil {
			return nil
		}
		if root == "" {
			if r.Type != "user" || r.PromptID != turn {
				continue
			}
			_, owned := reportDirectory(binding.Directory, r.Cwd)
			stamp, problem := time.Parse(time.RFC3339Nano, r.Timestamp)
			if r.Sidechain || r.Meta || r.Compact || r.UUID == "" || r.SessionID != binding.ProviderID || !filepath.IsAbs(r.Cwd) || !owned || claudeInputHash(claudeReportText(r.Message.Content), hash) != hash || problem != nil || stamp.UnixMilli() < since || stamp.After(time.Now().Add(time.Second)) {
				return nil
			}
			root, parent, promptTime = r.UUID, r.UUID, stamp
			continue
		}
		if r.Sidechain || (r.SessionID != "" && r.SessionID != binding.ProviderID) {
			return nil
		}
		if r.Cwd != "" {
			if _, owned := reportDirectory(binding.Directory, r.Cwd); !filepath.IsAbs(r.Cwd) || !owned {
				return nil
			}
		}
		switch r.Type {
		case "assistant":
			usage := r.Message.Usage
			code := claudeCompactionFailureCode(r)
			compaction := code != ""
			if result != nil || r.ParentUUID != parent || r.UUID == "" || r.SessionID != binding.ProviderID || (!compaction && !r.NoToolCall) || !r.APIError || r.Message.Model != "<synthetic>" || r.Message.Role != "assistant" || r.Message.StopReason != "stop_sequence" || usage == nil || usage.Input == nil || usage.Output == nil || *usage.Input != 0 || *usage.Output != 0 {
				return nil
			}
			var blocks []struct {
				Type string `json:"type"`
				Text string `json:"text"`
			}
			if json.Unmarshal(r.Message.Content, &blocks) != nil || len(blocks) != 1 || blocks[0].Type != "text" {
				return nil
			}
			if !compaction {
				code = claudeGatewayAdmissionCode(r, blocks[0].Text)
				if code == "" {
					return nil
				}
			}
			stamp, problem := time.Parse(time.RFC3339Nano, r.Timestamp)
			if problem != nil || stamp.Before(promptTime) || stamp.After(time.Now().Add(time.Second)) {
				return nil
			}
			result = &Result{State: "failed", ErrorCode: code, Summary: code, ExitCode: -1, FinishedMS: stamp.UnixMilli()}
		case "attachment":
			if result != nil || r.UUID == "" || r.ParentUUID != parent ||
				r.SessionID != binding.ProviderID || r.Cwd == "" ||
				(r.Attachment.Type != "date" && r.Attachment.Type != "model") {
				return nil
			}
			parent = r.UUID
		case "api-request", "api-request-blob", "api-request-shape", "file-history-snapshot":
			if result != nil {
				return nil
			}
		case "last-prompt", "mode", "permission-mode", "atis-latch", "cost-state", "ai-title":
		default:
			return nil
		}
	}
	return result
}

func claudeGatewayAdmissionCode(record claudeFailureRecord, text string) string {
	status := record.APIStatus
	if status == 400 && record.APIType == "api_error" && record.Failure == "unknown" &&
		text == "API Error: 400 MODEL_HTTP_400" {
		return "MODEL_HTTP_400"
	}
	if status == 429 && record.APIType == "api_error" && record.Failure == "rate_limit" &&
		text == "API Error: Request rejected (429) · MODEL_HTTP_429" {
		return "MODEL_HTTP_429"
	}
	if status != 402 && (status != 503 || record.Failure != "server_error") {
		return ""
	}
	body, ok := strings.CutPrefix(text, "API Error: "+strconv.Itoa(status)+" ")
	if !ok {
		return ""
	}
	var refusal struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	decoder := json.NewDecoder(strings.NewReader(body))
	if decoder.Decode(&refusal) != nil {
		return ""
	}
	suffix := strings.TrimSpace(body[decoder.InputOffset():])
	if status == 402 && refusal.Error.Code == "MODEL_PROXY_DAILY_LIMIT" && suffix == "" {
		return refusal.Error.Code
	}
	if status == 503 && refusal.Error.Code == "MODEL_ROUTE_NO_AVAILABLE_MEMBER" &&
		(suffix == "" || strings.HasPrefix(suffix, ". This is a server-side issue, usually temporary")) {
		return refusal.Error.Code
	}
	return ""
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

func claudeCompactionFailureCode(r claudeFailureRecord) string {
	if claudeCompactionRefusal(r) {
		return "CLAUDE_COMPACTION_FAILED"
	}
	if r.APIStatus != 0 || r.Failure != "invalid_request" {
		return ""
	}
	var blocks []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if json.Unmarshal(r.Message.Content, &blocks) != nil || len(blocks) != 1 || blocks[0].Type != "text" {
		return ""
	}
	if blocks[0].Text == "Prompt is too long · automatic compaction failed: API Error: 400 MODEL_HTTP_400" {
		return "CLAUDE_COMPACTION_INPUT_REJECTED"
	}
	return ""
}

func claudeCompactionRefusal(r claudeFailureRecord) bool {
	if r.APIStatus != 0 || r.Failure != "invalid_request" {
		return false
	}
	var blocks []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if json.Unmarshal(r.Message.Content, &blocks) != nil || len(blocks) != 1 || blocks[0].Type != "text" {
		return false
	}
	body, ok := strings.CutPrefix(blocks[0].Text, "Prompt is too long · automatic compaction failed: API Error: 503 ")
	if !ok {
		return false
	}
	var refusal struct {
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	return json.NewDecoder(strings.NewReader(body)).Decode(&refusal) == nil && refusal.Error.Code == "MODEL_ROUTE_NO_AVAILABLE_MEMBER"
}
