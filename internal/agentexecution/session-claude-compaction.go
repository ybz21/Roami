package agentexecution

import (
	"bytes"
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

const claudeLocalCommandCaveat = "<local-command-caveat>The command below was run directly in Claude Code, not sent to you as a request, and its output goes straight to the user. It's recorded here as context for later messages.</local-command-caveat>"

// A known stopped prefix cannot cover later execution hidden behind a compaction summary.
func claudeOnlyLocalCompaction(data []byte, stoppedDigest, provider, directory string) bool {
	if len(data) == 0 || data[len(data)-1] != '\n' || !nativeEvidenceDigest.MatchString(stoppedDigest) || provider == "" || directory == "" {
		return false
	}
	digest := sha256.New()
	found, boundary, summary, command, output := false, false, false, false, false
	compactPrompt := ""
	for _, line := range bytes.SplitAfter(data, []byte("\n")) {
		if len(line) == 0 {
			continue
		}
		if !found {
			digest.Write(line)
			found = hex.EncodeToString(digest.Sum(nil)) == stoppedDigest
			continue
		}
		var record claudeInterruptedRecord
		if json.Unmarshal(line, &record) != nil || record.Sidechain || record.SessionID != "" && record.SessionID != provider || record.Cwd != "" && record.Cwd != directory {
			return false
		}
		switch record.Type {
		case "file-history-snapshot", "last-prompt", "mode", "permission-mode", "atis-latch", "cost-state":
		case "system":
			if boundary || record.Subtype != "compact_boundary" || record.SessionID != provider || record.Cwd != directory {
				return false
			}
			boundary = true
		case "attachment":
			if !output {
				return false
			}
			switch record.Attachment.Type {
			case "file", "deferred_tools_delta", "agent_listing_delta", "skill_listing", "environment", "model", "hook_success":
			default:
				return false
			}
		case "user":
			if record.SessionID != provider || record.Cwd != directory || record.PromptID == "" {
				return false
			}
			// Local command records are strings; tool-result blocks are never allowed here.
			var text string
			if json.Unmarshal(record.Message.Content, &text) != nil {
				return false
			}
			if record.Meta && text == claudeLocalCommandCaveat {
				continue
			}
			if !boundary {
				return false
			}
			if compactPrompt == "" {
				compactPrompt = record.PromptID
			}
			if compactPrompt != record.PromptID {
				return false
			}
			if record.Compact && record.VisibleOnly && !summary && !command && !output {
				summary = true
				continue
			}
			if !record.Meta && !record.Compact && !record.VisibleOnly && summary && !command && strings.HasPrefix(text, "<command-name>/compact</command-name>\n") && strings.Contains(text, "<command-message>compact</command-message>") && strings.HasSuffix(text, "</command-args>") {
				command = true
				continue
			}
			if !record.Meta && !record.Compact && !record.VisibleOnly && command && !output && text == "<local-command-stdout>\x1b[2mCompacted (ctrl+o to see full summary)\x1b[22m</local-command-stdout>" {
				output = true
				continue
			}
			return false
		default:
			return false
		}
	}
	return found && boundary && summary && command && output
}

func (s Service) claudeUnsubmittedCompaction(state sessionLifecycle, spec Spec, receipt Receipt) (*Result, string) {
	if state.CompletedKey == "" || state.CompletedKey == spec.Key || receipt.Binding == nil {
		return nil, ""
	}
	priorDir, err := s.directory(state.CompletedKey)
	if err != nil {
		return nil, ""
	}
	var prior Spec
	var previous Receipt
	var stopped Result
	if readJSON(filepath.Join(priorDir, "spec.json"), &prior) != nil || prior.Key != state.CompletedKey || prior.Executor != "claude" || !prior.Persistent || readJSON(filepath.Join(priorDir, "receipt.json"), &previous) != nil || previous.Binding == nil || !reflect.DeepEqual(*previous.Binding, *receipt.Binding) || readJSON(filepath.Join(priorDir, "result.json"), &stopped) != nil || stopped.State != "failed" || stopped.ErrorCode != "CLAUDE_SESSION_INTERRUPTED" || stopped.InputStopped == nil || !*stopped.InputStopped || stopped.OutcomeKnown == nil || !*stopped.OutcomeKnown || state.PromptHash != workspaceHash(sessionPrompt(priorDir, prior)) {
		return nil, ""
	}
	path, info := claudeTranscriptPath(*receipt.Binding)
	if info == nil || info.Size() > 64<<20 {
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
	data, err := io.ReadAll(io.LimitReader(file, (64<<20)+1))
	if err != nil || len(data) > 64<<20 || !claudeOnlyLocalCompaction(data, stopped.StopEvidence, receipt.Binding.ProviderID, receipt.Binding.Directory) {
		return nil, ""
	}
	after, err := os.Stat(path)
	if err != nil || !os.SameFile(opened, after) || opened.Size() != after.Size() || !opened.ModTime().Equal(after.ModTime()) || int64(len(data)) != after.Size() {
		return nil, ""
	}
	digest := sha256.Sum256(data)
	return &Result{State: "failed", ErrorCode: "SESSION_COMPACTION_INPUT_NOT_EXECUTED", ExitCode: -1, FinishedMS: time.Now().UnixMilli()}, hex.EncodeToString(digest[:])
}
