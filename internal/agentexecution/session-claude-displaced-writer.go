package agentexecution

import (
	"context"
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

const claudeStoppedUnknown = "CLAUDE_STOP_CONFIRMED_OUTCOME_UNKNOWN"

var claudeCompactCommand = regexp.MustCompile(`^<command-name>/compact</command-name>\s*<command-message>compact</command-message>\s*<command-args>[^<]*</command-args>$`)

type displacedClaudeRecord struct {
	claudeFailureRecord
	Content   string `json:"content"`
	Operation string `json:"operation"`
}

func displacedClaudeRefusal(r claudeFailureRecord) bool {
	usage := r.Message.Usage
	if !r.APIError || r.Message.Model != "<synthetic>" || r.Message.Role != "assistant" ||
		r.Message.StopReason != "stop_sequence" || usage == nil || usage.Input == nil || usage.Output == nil ||
		*usage.Input != 0 || *usage.Output != 0 {
		return false
	}
	if claudeCompactionRefusal(r) {
		return true
	}
	var blocks []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	return r.Failure == "invalid_request" && r.APIStatus == 0 &&
		json.Unmarshal(r.Message.Content, &blocks) == nil && len(blocks) == 1 &&
		blocks[0].Type == "text" &&
		strings.HasPrefix(blocks[0].Text, "Prompt is too long · automatic compaction failed: API Error: 400 MODEL_HTTP_400")
}

func displacedClaudeStopEvidence(binding SessionBinding, marker, expected string, since, cancelledAt int64) (*Result, string) {
	path, info := claudeTranscriptPath(binding)
	if info == nil || since <= 0 || cancelledAt < since {
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
	digest := sha256.New()
	decoder := json.NewDecoder(io.TeeReader(io.LimitReader(file, (64<<20)+1), digest))
	const (
		idle = iota
		foreground
		command
		modelOutput
		compactOutput
	)
	phase := idle
	parent, promptID := "", ""
	var promptMS, finishedMS int64
	var seen, queued bool
	for {
		var r displacedClaudeRecord
		if err := decoder.Decode(&r); errors.Is(err, io.EOF) {
			break
		} else if err != nil {
			return nil, ""
		}
		stamp, err := time.Parse(time.RFC3339Nano, r.Timestamp)
		if !seen && (err != nil || stamp.UnixMilli() < since) {
			continue
		}
		if r.Type == "file-history-snapshot" && r.Timestamp == "" {
			continue
		}
		seen = true
		if err != nil || stamp.UnixMilli() < since || stamp.After(time.Now().Add(time.Second)) ||
			r.Sidechain || r.Compact || (r.SessionID != "" && r.SessionID != binding.ProviderID) {
			return nil, ""
		}
		if r.Type == "queue-operation" {
			switch {
			case r.Operation == "enqueue" && phase == foreground && !queued:
				queued = true
			case r.Operation == "dequeue" && queued:
				queued = false
			default:
				return nil, ""
			}
			continue
		}
		_, owned := reportDirectory(binding.Directory, r.Cwd)
		if !owned || !filepath.IsAbs(r.Cwd) || r.SessionID != binding.ProviderID || r.UUID == "" ||
			(parent != "" && r.ParentUUID != parent) {
			return nil, ""
		}
		parent = r.UUID
		text := claudeReportText(r.Message.Content)
		switch r.Type {
		case "user":
			if r.PromptID == "" || text == "" || strings.Contains(text, marker) || claudeInputHash(text, expected) == expected {
				return nil, ""
			}
			switch {
			case phase == idle && !queued && r.PromptID != promptID:
				promptID, promptMS, finishedMS = r.PromptID, stamp.UnixMilli(), 0
				switch {
				case r.Meta && strings.HasPrefix(text, "<local-command-caveat>") && strings.HasSuffix(text, "</local-command-caveat>"):
					phase = command
				case !r.Meta && !strings.HasPrefix(text, "<") && !strings.HasPrefix(text, "/"):
					phase = foreground
				default:
					return nil, ""
				}
			case phase == command && r.PromptID == promptID && !r.Meta && claudeModelCommand.MatchString(text):
				phase = modelOutput
			case phase == command && r.PromptID == promptID && !r.Meta && claudeCompactCommand.MatchString(text):
				phase = compactOutput
			case phase == modelOutput && r.PromptID == promptID && !r.Meta && strings.HasPrefix(text, "<local-command-stdout>") && strings.HasSuffix(text, "</local-command-stdout>"):
				phase = idle
			default:
				return nil, ""
			}
		case "system":
			if phase != compactOutput || r.Subtype != "local_command" || r.Meta ||
				!strings.HasPrefix(r.Content, "<local-command-stderr>Error during compaction: API Error: 400 MODEL_HTTP_400") ||
				!strings.HasSuffix(r.Content, "</local-command-stderr>") {
				return nil, ""
			}
			phase = idle
		case "attachment":
			if phase != foreground || (r.Attachment.Type != "model" && r.Attachment.Type != "date") {
				return nil, ""
			}
		case "assistant":
			if phase != foreground || stamp.UnixMilli() < promptMS || !displacedClaudeRefusal(r.claudeFailureRecord) {
				return nil, ""
			}
			phase, finishedMS = idle, stamp.UnixMilli()
		default:
			return nil, ""
		}
	}
	after, err := file.Stat()
	current, pathErr := os.Lstat(path)
	if phase != idle || queued || finishedMS <= cancelledAt || err != nil || pathErr != nil ||
		!os.SameFile(info, after) || !os.SameFile(info, current) || after.Size() != info.Size() ||
		!after.ModTime().Equal(info.ModTime()) || current.Mode().Perm()&0022 != 0 {
		return nil, ""
	}
	unknown := false
	return &Result{State: "failed", ErrorCode: claudeStoppedUnknown, Summary: claudeStoppedUnknown,
		OutcomeKnown: &unknown, ExitCode: -1, FinishedMS: finishedMS}, hex.EncodeToString(digest.Sum(nil))
}

// A later stopped foreground turn proves the writer is idle. It carries no result for the displaced input.
func (s Service) reconcileDisplacedClaudeWriter(ctx context.Context, key, dir, path string, spec Spec, receipt Receipt, state *sessionLifecycle, since int64, expected string) (Status, error) {
	empty := Status{}
	cancelPath := filepath.Join(dir, "cancel.json")
	var intent struct {
		Cancel bool `json:"cancel"`
	}
	cancel, err := os.Lstat(cancelPath)
	if err != nil || !cancel.Mode().IsRegular() || readJSON(cancelPath, &intent) != nil || !intent.Cancel || !spec.Persistent ||
		spec.PromptFormat != "" || state.PromptHash == "" || state.PromptHash == expected ||
		state.TurnID == "" || receipt.Workspace.Directory != state.Binding.Directory {
		return empty, fmt.Errorf("SESSION_RECONCILIATION_SCOPE_REQUIRED")
	}
	marker := "Roami delegated task [" + filepath.Base(dir) + "]"
	return s.settleClaudeObservedOutcome(ctx, key, dir, path, receipt, state, state.TurnID, state.PromptHash,
		func() (*Result, string, map[string]int64) {
			current, err := os.Lstat(cancelPath)
			if err != nil || !os.SameFile(cancel, current) || !cancel.ModTime().Equal(current.ModTime()) {
				return nil, "", nil
			}
			result, digest := displacedClaudeStopEvidence(state.Binding, marker, expected, since, cancel.ModTime().UnixMilli())
			return result, digest, nil
		})
}
