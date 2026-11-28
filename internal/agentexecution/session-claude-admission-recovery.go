package agentexecution

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"github.com/ybz21/Roami/internal/fsguard"
)

const claudeAdmissionRecoverySuffixLimit = 64 << 10

// A settled gateway refusal records the digest before local model and exit receipts.
func claudeAdmissionRecoveryProven(state sessionLifecycle, dir string, result Result) bool {
	if result.State != "failed" || !nativeEvidenceDigest.MatchString(result.StopEvidence) {
		return false
	}
	spec, err := os.Stat(filepath.Join(dir, "spec.json"))
	if err != nil {
		return false
	}
	binding := state.Binding
	path, info := claudeTranscriptPath(binding)
	if info == nil {
		return false
	}
	file, err := fsguard.OpenReadNoFollow(path)
	if err != nil {
		return false
	}
	defer file.Close()
	opened, err := file.Stat()
	if err != nil || !sameClaudeInputFile(info, opened) {
		return false
	}
	offset, suffix := claudeRecoveryPrefix(file, info.Size(), result.StopEvidence)
	if offset == 0 || !validClaudeAdmissionSuffix(suffix, binding, state) {
		return false
	}
	refusal := readClaudeAdmissionRejection(binding, state.TurnID, state.PromptHash, spec.ModTime().UnixMilli(), io.NewSectionReader(file, 0, offset))
	after, err := file.Stat()
	current, problem := os.Lstat(path)
	return refusal != nil && refusal.ErrorCode == result.ErrorCode && refusal.FinishedMS == result.FinishedMS &&
		err == nil && problem == nil && sameClaudeInputFile(info, after) && sameClaudeInputFile(info, current)
}

func claudeRecoveryPrefix(file *os.File, size int64, evidence string) (int64, []byte) {
	start := max(0, size-claudeAdmissionRecoverySuffixLimit)
	digest := sha256.New()
	if _, err := io.CopyN(digest, file, start); err != nil {
		return 0, nil
	}
	tail, err := io.ReadAll(io.LimitReader(file, claudeAdmissionRecoverySuffixLimit+1))
	if err != nil || int64(len(tail)) != size-start {
		return 0, nil
	}
	expected, _ := hex.DecodeString(evidence)
	for len(tail) != 0 {
		length := bytes.IndexByte(tail, '\n') + 1
		if length == 0 {
			length = len(tail)
		}
		digest.Write(tail[:length])
		start += int64(length)
		tail = tail[length:]
		if bytes.Equal(digest.Sum(nil), expected) {
			return start, tail
		}
	}
	return 0, nil
}

type claudeAdmissionLocalRecord struct {
	claudeInterruptedRecord
	Content string `json:"content"`
	Run     *struct {
		Name string  `json:"command"`
		Args *string `json:"args"`
	} `json:"commandRun"`
}

func (r claudeAdmissionLocalRecord) ownedBy(binding SessionBinding) bool {
	return r.SessionID == binding.ProviderID && r.Cwd != "" &&
		codexThreadID.MatchString(r.UUID) && claudeInputDirectory(binding, r.Cwd)
}

var claudeModelDefaultNotice = regexp.MustCompile(`^\n     ANTHROPIC_MODEL is set to ` + "`[a-zA-Z0-9._:/-]+`" + ` — new sessions use that while it is set$`)

func claudeSameDefaultModelReceipt(value, model string) bool {
	if model == "" {
		return false
	}
	value = strings.NewReplacer("\x1b[2m", "", "\x1b[22m", "").Replace(value)
	value, ok := strings.CutPrefix(value, "<local-command-stdout>Set model to `"+model+"` and saved as your default for new sessions")
	if !ok {
		return false
	}
	value, ok = strings.CutSuffix(value, "</local-command-stdout>")
	return ok && (value == "" || claudeModelDefaultNotice.MatchString(value))
}

func validClaudeAdmissionSuffix(suffix []byte, binding SessionBinding, state sessionLifecycle) bool {
	if len(suffix) == 0 {
		return true
	}
	if !state.EndedIdle || suffix[len(suffix)-1] != '\n' {
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(suffix))
	closed := false
	for {
		var entry claudeAdmissionLocalRecord
		if err := decoder.Decode(&entry); err == io.EOF {
			return closed
		} else if err != nil || entry.Sidechain || entry.Compact || entry.SessionID != "" && entry.SessionID != binding.ProviderID ||
			entry.Cwd != "" && !claudeInputDirectory(binding, entry.Cwd) {
			return false
		}
		switch entry.Type {
		case "file-history-snapshot", "last-prompt", "mode", "permission-mode", "atis-latch", "cost-state", "ai-title":
			continue
		case "system":
			var output claudeAdmissionLocalRecord
			if closed || !entry.ownedBy(binding) || entry.Subtype != "local_command" || entry.Meta ||
				entry.Run != nil || !claudeModelPickerCommand.MatchString(entry.Content) ||
				decoder.Decode(&output) != nil || output.Type != "system" || output.Subtype != "local_command" ||
				output.Sidechain || output.Meta || output.Compact || !output.ownedBy(binding) ||
				output.Parent != entry.UUID || output.UUID == entry.UUID || output.Cwd != entry.Cwd ||
				output.Run == nil || output.Run.Name != "model" || output.Run.Args == nil || *output.Run.Args != "" ||
				output.Content != "<local-command-stdout>Kept model as `"+state.configuredModel()+"`</local-command-stdout>" {
				return false
			}
		case "user":
			command, output := claudeAdmissionLocalCommand(decoder, entry, binding)
			switch {
			case closed:
				return false
			case claudeLocalExitCommand.MatchString(command) && claudeLocalExitReceipt(output):
				closed = true
			case claudeModelPickerCommand.MatchString(command) && claudeSameDefaultModelReceipt(output, state.configuredModel()):
			default:
				return false
			}
		default:
			return false
		}
	}
}

func claudeAdmissionLocalCommand(decoder *json.Decoder, caveat claudeAdmissionLocalRecord, binding SessionBinding) (string, string) {
	if !caveat.ownedBy(binding) || !caveat.Meta || caveat.PromptID == "" || claudeReportText(caveat.Message.Content) != claudeLocalCommandCaveat {
		return "", ""
	}
	previous := caveat
	var text [2]string
	for index := range text {
		var entry claudeAdmissionLocalRecord
		if decoder.Decode(&entry) != nil || entry.Type != "user" || !entry.ownedBy(binding) ||
			entry.Meta || entry.Sidechain || entry.Compact || entry.UUID == previous.UUID ||
			entry.Parent != previous.UUID || entry.PromptID != caveat.PromptID || entry.Cwd != caveat.Cwd ||
			json.Unmarshal(entry.Message.Content, &text[index]) != nil {
			return "", ""
		}
		previous = entry
	}
	return text[0], text[1]
}
