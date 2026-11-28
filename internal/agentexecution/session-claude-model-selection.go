package agentexecution

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"regexp"
	"strings"

	"github.com/ybz21/Roami/internal/fsguard"
)

const claudeModelSelectionLimit = 1 << 20
const claudeModelAnchorLimit = 8 << 10

var claudeModelPickerCommand = regexp.MustCompile(`^<command-name>/model</command-name>\n[ \t]*<command-message>model</command-message>\n[ \t]*<command-args></command-args>$`)

type claudeModelAnchor struct {
	Device uint64 `json:"device"`
	Inode  uint64 `json:"inode"`
	Offset int64  `json:"offset"`
	Digest string `json:"sha256"`
}

type claudeModelProof struct {
	PromptID string `json:"promptId"`
	Digest   string `json:"sourceSha256"`
}

func claudeModelCheckpoint(binding SessionBinding) (claudeModelAnchor, bool) {
	path, info := claudeTranscriptPath(binding)
	if info == nil {
		return claudeModelAnchor{}, false
	}
	file, err := fsguard.OpenReadNoFollow(path)
	if err != nil {
		return claudeModelAnchor{}, false
	}
	defer file.Close()
	anchor, ok := claudeModelSnapshot(file, info, info.Size())
	if after, err := os.Lstat(path); err != nil || !sameClaudeInputFile(info, after) {
		return claudeModelAnchor{}, false
	}
	return anchor, ok
}

// Anchor the append so model control never needs to reread or return the old conversation.
func claudeModelSnapshot(file *os.File, info os.FileInfo, offset int64) (claudeModelAnchor, bool) {
	if offset <= 0 || offset > info.Size() {
		return claudeModelAnchor{}, false
	}
	if opened, err := file.Stat(); err != nil || !sameClaudeInputFile(info, opened) {
		return claudeModelAnchor{}, false
	}
	device, inode, ok := fsguard.FileIdentity(info)
	if !ok || inode == 0 {
		return claudeModelAnchor{}, false
	}
	length := min(offset, int64(claudeModelAnchorLimit))
	tail := make([]byte, length)
	if _, err := file.ReadAt(tail, offset-length); err != nil || tail[len(tail)-1] != '\n' {
		return claudeModelAnchor{}, false
	}
	digest := sha256.Sum256(tail)
	return claudeModelAnchor{Device: device, Inode: inode, Offset: offset, Digest: hex.EncodeToString(digest[:])}, true
}

func claudeSessionModelProof(binding SessionBinding, anchor claudeModelAnchor, models []string) (claudeModelProof, bool) {
	path, info := claudeTranscriptPath(binding)
	if info == nil || anchor.Offset <= 0 || info.Size() <= anchor.Offset || info.Size()-anchor.Offset > claudeModelSelectionLimit {
		return claudeModelProof{}, false
	}
	file, err := fsguard.OpenReadNoFollow(path)
	if err != nil {
		return claudeModelProof{}, false
	}
	defer file.Close()
	if actual, ok := claudeModelSnapshot(file, info, anchor.Offset); !ok || actual != anchor {
		return claudeModelProof{}, false
	}
	data, err := io.ReadAll(io.NewSectionReader(file, anchor.Offset, info.Size()-anchor.Offset))
	if err != nil || int64(len(data)) != info.Size()-anchor.Offset {
		return claudeModelProof{}, false
	}
	if after, err := os.Lstat(path); err != nil || !sameClaudeInputFile(info, after) {
		return claudeModelProof{}, false
	}
	prompt, ok := claudeSessionModelSuffix(data, binding, models)
	if !ok {
		return claudeModelProof{}, false
	}
	digest := sha256.Sum256(data)
	return claudeModelProof{PromptID: prompt, Digest: hex.EncodeToString(digest[:])}, true
}

func claudeSessionModelSuffix(data []byte, binding SessionBinding, models []string) (string, bool) {
	if len(data) == 0 || data[len(data)-1] != '\n' || binding.ProviderID == "" || binding.Directory == "" {
		return "", false
	}
	// The Claude session can change directories without changing its workspace binding.
	var prompt, directory string
	phase := 0
	for _, line := range bytes.Split(data[:len(data)-1], []byte("\n")) {
		var record claudeInterruptedRecord
		if json.Unmarshal(line, &record) != nil || record.Sidechain ||
			(record.SessionID != "" && record.SessionID != binding.ProviderID) ||
			(record.Cwd != "" && !claudeInputDirectory(binding, record.Cwd)) {
			return "", false
		}
		switch record.Type {
		case "file-history-snapshot", "last-prompt", "mode", "permission-mode", "atis-latch", "cost-state", "ai-title":
			continue
		case "system":
			if record.Subtype == "stop_hook_summary" || record.Subtype == "turn_duration" {
				continue
			}
		case "user":
			if record.Compact || record.SessionID != binding.ProviderID || record.Cwd == "" || record.PromptID == "" {
				return "", false
			}
			var value string
			if json.Unmarshal(record.Message.Content, &value) != nil {
				return "", false
			}
			switch phase {
			case 0:
				if record.Meta && value == claudeLocalCommandCaveat {
					prompt, directory, phase = record.PromptID, record.Cwd, 1
					continue
				}
			case 1:
				if !record.Meta && record.PromptID == prompt && record.Cwd == directory && claudeModelPickerCommand.MatchString(value) {
					phase = 2
					continue
				}
			case 2:
				if !record.Meta && record.PromptID == prompt && record.Cwd == directory && claudeSessionModelOutput(value, models) {
					phase = 3
					continue
				}
			}
		}
		return "", false
	}
	return prompt, phase == 3
}

func claudeSessionModelOutput(value string, models []string) bool {
	model, prefix := strings.CutPrefix(value, "<local-command-stdout>Set model to `")
	model, suffix := strings.CutSuffix(model, "` for this session only</local-command-stdout>")
	if !prefix || !suffix {
		return false
	}
	for _, allowed := range models {
		if allowed != "" && model == allowed {
			return true
		}
	}
	return false
}
