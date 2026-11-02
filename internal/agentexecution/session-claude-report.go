package agentexecution

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"syscall"
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
}

type claudeReportRecord struct {
	Type      string `json:"type"`
	SessionID string `json:"sessionId"`
	PromptID  string `json:"promptId"`
	Cwd       string `json:"cwd"`
	Sidechain bool   `json:"isSidechain"`
	Meta      bool   `json:"isMeta"`
	Compact   bool   `json:"isCompactSummary"`
	Message   struct {
		Content    json.RawMessage `json:"content"`
		StopReason string          `json:"stop_reason"`
	} `json:"message"`
}

type claudeReportSnapshot struct {
	Path       string            `json:"path"`
	Size       int64             `json:"size"`
	ModifiedNS int64             `json:"modifiedNs"`
	Inode      uint64            `json:"inode"`
	ProviderID string            `json:"providerId"`
	PromptID   string            `json:"promptId"`
	PromptHash string            `json:"promptHash"`
	Directory  string            `json:"directory"`
	Progress   *ReportedProgress `json:"progress"`
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

func claudeReportedProgress(binding SessionBinding, turn, promptHash, launchDir string) *ReportedProgress {
	if !codexThreadID.MatchString(binding.ProviderID) || turn == "" || promptHash == "" {
		return nil
	}
	home := os.Getenv("CLAUDE_CONFIG_DIR")
	if home == "" {
		user, err := os.UserHomeDir()
		if err != nil {
			return nil
		}
		home = filepath.Join(user, ".claude")
	}
	root, err := filepath.EvalSymlinks(filepath.Join(home, "projects"))
	if err != nil {
		return nil
	}
	paths, err := filepath.Glob(filepath.Join(root, "*", binding.ProviderID+".jsonl"))
	if err != nil || len(paths) != 1 {
		return nil
	}
	path := paths[0]
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil || resolved != path {
		return nil
	}
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0022 != 0 || info.Size() > 64<<20 {
		return nil
	}
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(owner.Uid) != os.Geteuid() {
		return nil
	}
	snapshot := claudeReportSnapshot{Path: path, Size: info.Size(), ModifiedNS: info.ModTime().UnixNano(), Inode: owner.Ino, ProviderID: binding.ProviderID, PromptID: turn, PromptHash: promptHash, Directory: binding.Directory}
	cache := filepath.Join(launchDir, "reported-progress.json")
	var previous claudeReportSnapshot
	if readJSON(cache, &previous) == nil && previous.Path == snapshot.Path && previous.Size == snapshot.Size && previous.ModifiedNS == snapshot.ModifiedNS && previous.Inode == snapshot.Inode && previous.ProviderID == snapshot.ProviderID && previous.PromptID == snapshot.PromptID && previous.PromptHash == snapshot.PromptHash && previous.Directory == snapshot.Directory {
		return previous.Progress
	}
	file, err := os.Open(path)
	if err != nil {
		return nil
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !os.SameFile(info, opened) {
		return nil
	}
	hash := sha256.New()
	decoder := json.NewDecoder(io.TeeReader(io.LimitReader(file, (64<<20)+1), hash))
	matched := false
	var progress *ReportedProgress
	valid := true
	for {
		var record claudeReportRecord
		if err = decoder.Decode(&record); errors.Is(err, io.EOF) {
			break
		} else if err != nil {
			valid = false
			break
		}
		if record.Sidechain || record.Type != "user" && record.Type != "assistant" {
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
			if record.PromptID == turn && workspaceHash(text) == promptHash {
				directory, ok := reportDirectory(binding.Directory, record.Cwd)
				if !ok || directory != binding.Directory {
					valid = false
					break
				}
				matched = true
			}
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
		return nil
	}
	if !valid {
		progress = nil
	}
	if progress != nil {
		progress.SourceDigest = hex.EncodeToString(hash.Sum(nil))
	}
	snapshot.Progress = progress
	_ = writeJSON(cache, snapshot)
	return progress
}
