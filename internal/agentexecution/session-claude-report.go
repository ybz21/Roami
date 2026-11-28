package agentexecution

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/fsguard"
)

// Reported progress never supplies stop evidence or changes the execution outcome.
type ReportedProgress struct {
	Source       string `json:"source"`
	Summary      string `json:"summary"`
	Directory    string `json:"directory"`
	ProviderID   string `json:"providerConversationId"`
	PromptID     string `json:"promptId"`
	SourceDigest string `json:"sourceDigest"`
	ObservedMS   int64  `json:"observedMs"`
	ActivityMS   int64  `json:"activityMs,omitempty"`
}

type claudeReportRecord struct {
	Type       string `json:"type"`
	SessionID  string `json:"sessionId"`
	PromptID   string `json:"promptId"`
	Cwd        string `json:"cwd"`
	Sidechain  bool   `json:"isSidechain"`
	Meta       bool   `json:"isMeta"`
	Compact    bool   `json:"isCompactSummary"`
	Timestamp  string `json:"timestamp"`
	Attachment struct {
		Type string `json:"type"`
	} `json:"attachment"`
	Message struct {
		Content    json.RawMessage `json:"content"`
		StopReason string          `json:"stop_reason"`
		Model      string          `json:"model"`
	} `json:"message"`
}

type claudeReportSnapshot struct {
	Format       int                 `json:"format"`
	Path         string              `json:"path"`
	Size         int64               `json:"size"`
	ModifiedNS   int64               `json:"modifiedNs"`
	Inode        uint64              `json:"inode"`
	ProviderID   string              `json:"providerId"`
	PromptID     string              `json:"promptId"`
	PromptHash   string              `json:"promptHash"`
	Directory    string              `json:"directory"`
	Progress     *ReportedProgress   `json:"progress"`
	ToolError    *ReportedToolError  `json:"toolError,omitempty"`
	ToolActivity *NativeToolActivity `json:"toolActivity,omitempty"`
}

func claudeReportText(raw json.RawMessage) string {
	var scalar string
	if json.Unmarshal(raw, &scalar) == nil {
		return scalar
	}
	var blocks []struct {
		Type string `json:"type"`
		Text string `json:"text"`
	}
	if json.Unmarshal(raw, &blocks) != nil {
		return ""
	}
	parts := []string{}
	for _, block := range blocks {
		if block.Type == "text" {
			parts = append(parts, block.Text)
		}
	}
	return strings.Join(parts, "\n")
}

func reportDirectory(root, value string) (string, bool) {
	directory, err := canonicalWorkspace(value)
	if err != nil {
		return "", false
	}
	relative, err := filepath.Rel(root, directory)
	return directory, err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(os.PathSeparator))
}

func claudeTranscriptPath(binding SessionBinding) (string, os.FileInfo) {
	if !codexThreadID.MatchString(binding.ProviderID) {
		return "", nil
	}
	home := binding.ProviderHome
	if home == "" {
		home = os.Getenv("CLAUDE_CONFIG_DIR")
	}
	if home == "" {
		user, err := os.UserHomeDir()
		if err != nil {
			return "", nil
		}
		home = filepath.Join(user, ".claude")
	}
	root, err := filepath.EvalSymlinks(filepath.Join(home, "projects"))
	if err != nil {
		return "", nil
	}
	paths, err := filepath.Glob(filepath.Join(root, "*", binding.ProviderID+".jsonl"))
	if err != nil || len(paths) != 1 {
		return "", nil
	}
	path := paths[0]
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return "", nil
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0022 != 0 || info.Size() > 64<<20 {
		return "", nil
	}
	if !fsguard.OwnedByCurrentUser(info) {
		return "", nil
	}
	return path, info
}

func claudeReportedProgress(binding SessionBinding, turn, promptHash, launchDir string) *ReportedProgress {
	progress, _ := claudeReportedState(binding, turn, promptHash, launchDir)
	return progress
}

func claudeReportedState(binding SessionBinding, turn, promptHash, launchDir string) (*ReportedProgress, *ReportedToolError) {
	progress, report, _ := claudeReport(binding, turn, promptHash, launchDir)
	return progress, report
}

func claudeReport(binding SessionBinding, turn, promptHash, launchDir string) (*ReportedProgress, *ReportedToolError, *NativeToolActivity) {
	return claudeReportWithExit(binding, turn, promptHash, launchDir, false)
}

var claudeLocalExitCommand = regexp.MustCompile(`^<command-name>/exit</command-name>\n[ \t]*<command-message>exit</command-message>\n[ \t]*<command-args></command-args>$`)

func claudeLocalExitReceipt(value string) bool {
	return value == "<local-command-stdout>Bye!</local-command-stdout>" ||
		value == "<local-command-stdout>Goodbye!</local-command-stdout>"
}

func claudeReportWithExit(binding SessionBinding, turn, promptHash, launchDir string, stoppedIdle bool) (*ReportedProgress, *ReportedToolError, *NativeToolActivity) {
	if turn == "" || promptHash == "" {
		return nil, nil, nil
	}
	path, info := claudeTranscriptPath(binding)
	if info == nil {
		return nil, nil, nil
	}
	_, ino, _ := fsguard.FileIdentity(info)

	snapshot := claudeReportSnapshot{Format: 3, Path: path, Size: info.Size(), ModifiedNS: info.ModTime().UnixNano(), Inode: ino, ProviderID: binding.ProviderID, PromptID: turn, PromptHash: promptHash, Directory: binding.Directory}
	cache := filepath.Join(launchDir, "reported-progress.json")
	if stoppedIdle {
		cache = filepath.Join(launchDir, "reported-recovery-progress.json")
	}
	var previous claudeReportSnapshot
	if readJSON(cache, &previous) == nil && previous.Format == snapshot.Format && previous.Path == snapshot.Path && previous.Size == snapshot.Size && previous.ModifiedNS == snapshot.ModifiedNS && previous.Inode == snapshot.Inode && previous.ProviderID == snapshot.ProviderID && previous.PromptID == snapshot.PromptID && previous.PromptHash == snapshot.PromptHash && previous.Directory == snapshot.Directory {
		return previous.Progress, previous.ToolError, previous.ToolActivity
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, nil, nil
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return nil, nil, nil
	}
	hash := sha256.New()
	decoder := json.NewDecoder(io.TeeReader(io.LimitReader(file, (64<<20)+1), hash))
	matched := false
	var progress *ReportedProgress
	observation := claudeToolErrorState{tools: map[string]string{}, classifierErrors: map[string]int{}}
	valid := true
	var exitPrompt, exitDirectory string
	exitPhase := 0
	activityKnown, activityMS := true, int64(0)
	for {
		var record claudeReportRecord
		if err = decoder.Decode(&record); errors.Is(err, io.EOF) {
			break
		} else if err != nil {
			valid = false
			break
		}
		if stoppedIdle && matched && progress != nil {
			owner := record.Type == "user" && !record.Sidechain && !record.Compact &&
				record.SessionID == binding.ProviderID && record.PromptID != "" && record.PromptID != turn
			if exitPhase > 0 || owner && record.Meta && claudeReportText(record.Message.Content) == claudeLocalCommandCaveat {
				var local string
				if !owner || json.Unmarshal(record.Message.Content, &local) != nil {
					valid = false
					break
				}
				switch {
				case exitPhase == 0 && claudeInputDirectory(binding, record.Cwd):
					exitPrompt, exitDirectory, exitPhase = record.PromptID, record.Cwd, 1
				case exitPhase == 1 && !record.Meta && record.PromptID == exitPrompt && record.Cwd == exitDirectory && claudeLocalExitCommand.MatchString(local):
					exitPhase = 2
				case exitPhase == 2 && !record.Meta && record.PromptID == exitPrompt && record.Cwd == exitDirectory && claudeLocalExitReceipt(local):
					exitPhase = 3
				default:
					valid = false
				}
				if !valid {
					break
				}
				continue
			}
		}
		if record.Type == "user" || record.Type == "assistant" || record.Type == "api-request" || record.Type == "api-request-shape" || record.Type == "api-request-blob" || record.Type == "attachment" && record.Attachment.Type == "queued_command" {
			stamp, problem := time.Parse(time.RFC3339Nano, record.Timestamp)
			if problem != nil {
				activityKnown = false
			} else {
				// A later timed action also bounds earlier untimed diagnostics.
				activityKnown = true
				if stamp.UnixMilli() > activityMS {
					activityMS = stamp.UnixMilli()
				}
			}
		}
		if record.Sidechain || record.Type != "user" && record.Type != "assistant" {
			if matched && record.Sidechain {
				observation.incomplete = true
			}
			continue
		}
		if record.SessionID != binding.ProviderID {
			valid = false
			break
		}
		text := claudeReportText(record.Message.Content)
		if record.Type == "user" && !record.Meta && !record.Compact && text != "" {
			if matched && record.PromptID != turn {
				valid = false
				break
			}
			if matched {
				observation.incomplete = true
			}
			if matched && claudeInputHash(text, promptHash) != promptHash {
				observation.discarded = true
				observation.report = nil
			}
			if record.PromptID == turn && claudeInputHash(text, promptHash) == promptHash {
				_, ok := reportDirectory(binding.Directory, record.Cwd)
				if !ok {
					valid = false
					break
				}
				matched = true
			}
		}
		if matched && (record.PromptID == "" || record.PromptID == turn) {
			observation.observe(binding, turn, record)
		} else if matched {
			observation.incomplete = true
		}
		if matched && record.Type == "assistant" && record.Message.StopReason == "end_turn" && text != "" {
			directory, ok := reportDirectory(binding.Directory, record.Cwd)
			if !ok {
				valid = false
				break
			}
			progress = &ReportedProgress{Source: "provider_transcript", Summary: truncate(text, 32000), Directory: directory, ProviderID: binding.ProviderID, PromptID: turn, ObservedMS: info.ModTime().UnixMilli()}
		}
	}
	after, err := file.Stat()
	if err != nil || !os.SameFile(info, after) || after.Size() != info.Size() || !after.ModTime().Equal(info.ModTime()) {
		return nil, nil, nil
	}
	valid = valid && (exitPhase == 0 || exitPhase == 3)
	if !valid {
		progress = nil
		observation.report = nil
	}
	digest := hex.EncodeToString(hash.Sum(nil))
	if progress != nil {
		progress.SourceDigest = digest
		if activityKnown {
			progress.ActivityMS = activityMS
		}
	}
	snapshot.Progress = progress
	snapshot.ToolError = observation.report
	if valid && matched && !observation.discarded && !observation.incomplete && observation.activity.LastToolResultMS > 0 {
		observation.activity.ProviderID = binding.ProviderID
		observation.activity.PromptID = turn
		observation.activity.SourceDigest = digest
		observation.activity.PendingTools = len(observation.tools)
		if observation.report != nil {
			observation.activity.ClassifierTool = observation.report.Tool
			observation.activity.ConsecutiveClassifierErrors = observation.classifierErrors[observation.report.Tool]
		}
		snapshot.ToolActivity = &observation.activity
	}
	_ = writeJSON(cache, snapshot)
	return progress, observation.report, snapshot.ToolActivity
}
