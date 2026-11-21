package agentexecution

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"io"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
)

type ClaudeModelInputEvidence struct {
	ProviderID    string             `json:"providerId"`
	PromptID      string             `json:"promptId"`
	RequestSHA256 string             `json:"requestSha256"`
	Capabilities  []ClaudeInputRead  `json:"capabilities"`
	Images        []ClaudeInputImage `json:"images"`
}

type ClaudeInputRead struct {
	ToolCallID     string `json:"toolCallId"`
	ResponseSHA256 string `json:"responseSha256"`
}

type ClaudeInputImage struct {
	MIME   string `json:"mime"`
	SHA256 string `json:"sha256"`
}

var (
	claudeRequestSHA        = regexp.MustCompile("^[a-f0-9]{64}$")
	claudeCapabilityID      = regexp.MustCompile("^native-main-[a-f0-9]{64}$")
	claudeCapabilityCommand = regexp.MustCompile(`^[ \t]*(?:[A-Za-z0-9_./$-]+|"[^"\r\n]+"|'[^'\r\n]+')[ \t]+agent[ \t]+capability[ \t]+call[ \t]+([A-Za-z][A-Za-z0-9_-]{0,127})[ \t]+--context[ \t]+(?:[A-Za-z0-9_./$\{\}-]+|"[^"\r\n]+"|'[^'\r\n]+')[ \t]+--call[ \t]+(?:([A-Za-z0-9_-]+)|"([A-Za-z0-9_-]+)"|'([A-Za-z0-9_-]+)')(?:[ \t]+--input[ \t]+|[ \t]*$)`)
)

const claudeInputProofLimit = 512
const claudeInputBatchBytes = 24 << 20

type claudeModelInputRecord struct {
	claudeInterruptedRecord
	RequestID       string   `json:"id"`
	Source          string   `json:"querySource"`
	RequestDigest   string   `json:"requestDigest"`
	Base            string   `json:"base"`
	Keep            *int     `json:"keep"`
	Tail            []string `json:"tail"`
	SourceAssistant string   `json:"sourceToolAssistantUUID"`
}

type claudeRequestDelta struct {
	base   *claudeRequestDelta
	keep   int
	tail   []string
	length int
	digest string
}

// A delta retains exactly the prefix selected by the provider.
func (d *claudeRequestDelta) messageHashes() map[string]bool {
	exact := make(map[string]bool, d.length)
	for take := d.length; d != nil && take > 0; d = d.base {
		if take > d.keep {
			for _, hash := range d.tail[:take-d.keep] {
				exact[hash] = true
			}
			take = d.keep
		}
	}
	return exact
}

type claudeInputTool struct {
	assistant string
	name      string
}

type claudeInputFingerprint struct {
	message      string
	capabilities []ClaudeInputRead
	images       []ClaudeInputImage
}

type claudeInputBatch struct {
	blocks []map[string]any
	proof  claudeInputFingerprint
	count  int
	bytes  int
}

func (b *claudeInputBatch) add(blocks []map[string]any, proof claudeInputFingerprint, size int) {
	b.count++
	b.bytes += size
	if b.bytes > claudeInputBatchBytes || len(b.blocks)+len(blocks) > claudeInputProofLimit {
		b.bytes = claudeInputBatchBytes + 1
		b.blocks, b.proof = nil, claudeInputFingerprint{}
		return
	}
	b.blocks = append(b.blocks, blocks...)
	b.proof.capabilities = append(b.proof.capabilities, proof.capabilities...)
	b.proof.images = append(b.proof.images, proof.images...)
}

// Claude can combine a parallel tool batch into one user message.
func (b claudeInputBatch) forRequest(tail []string) claudeInputFingerprint {
	if b.count < 2 || len(b.proof.capabilities)+len(b.proof.images) == 0 {
		return claudeInputFingerprint{}
	}
	b.proof.message = claudeInputDigest(map[string]any{"role": "user", "content": b.blocks})
	if !slices.Contains(tail, b.proof.message) {
		return claudeInputFingerprint{}
	}
	return b.proof
}

func claudeModelInput(reader io.Reader, binding SessionBinding, turn, promptHash, capability, request string) *ClaudeModelInputEvidence {
	if turn == "" || request == "" || !claudeRequestSHA.MatchString(promptHash) {
		return nil
	}
	requests := make(map[string]*claudeRequestDelta)
	linked := make(map[string]bool)
	tools := make(map[string]claudeInputTool)
	var observed []claudeInputFingerprint
	var batch claudeInputBatch
	var latest, selected *claudeRequestDelta
	current, selectedTool := false, ""
	decoder := json.NewDecoder(reader)
	for {
		var record claudeModelInputRecord
		if err := decoder.Decode(&record); err == io.EOF {
			break
		} else if err != nil {
			return nil
		}
		if record.Type == "api-request" && record.Source == "repl_main_thread" {
			delta := claudeModelRequest(record, requests, binding.ProviderID)
			if delta == nil {
				return nil
			}
			requests[record.RequestID] = delta
			if current {
				if fingerprint := batch.forRequest(delta.tail); fingerprint.message != "" {
					observed = append(observed, fingerprint)
					if len(observed) > claudeInputProofLimit {
						return nil
					}
				}
				batch = claudeInputBatch{}
				latest = delta
			}
			continue
		}
		if record.Sidechain {
			continue
		}
		if record.Type == "user" && !record.Meta && !record.Compact && !record.VisibleOnly {
			if prompt := claudeReportText(record.Message.Content); prompt != "" {
				if current {
					return nil
				}
				if record.PromptID == turn && claudeInputHash(prompt, promptHash) == promptHash {
					if record.SessionID != binding.ProviderID || record.UUID == "" || !filepath.IsAbs(record.Cwd) || !claudeInputDirectory(binding, record.Cwd) {
						return nil
					}
					linked[record.UUID], current = true, true
					continue
				}
			}
		}
		if !current || !(linked[record.Parent] || linked[record.LogicalParent]) {
			continue
		}
		if record.Compact || record.Subtype == "compact_boundary" || record.Subtype == "stop_hook_summary" ||
			record.SessionID != "" && record.SessionID != binding.ProviderID ||
			record.Cwd != "" && !claudeInputDirectory(binding, record.Cwd) || linked[record.UUID] {
			return nil
		}
		if record.UUID != "" {
			linked[record.UUID] = true
		}
		if record.VisibleOnly || record.Meta || record.Type != "assistant" && record.Type != "user" {
			continue
		}
		var blocks []claudeInterruptedBlock
		if content := bytes.TrimSpace(record.Message.Content); len(content) == 0 || content[0] != '[' {
			continue
		}
		if json.Unmarshal(record.Message.Content, &blocks) != nil || record.SessionID != binding.ProviderID ||
			record.PromptID != "" && record.PromptID != turn {
			return nil
		}
		if record.Type == "assistant" {
			for _, block := range blocks {
				if block.Type != "tool_use" || block.ID == "" || !synchronousClaudeTool(block) ||
					(block.Name != "Bash" && block.Name != "Read") {
					continue
				}
				if tools[block.ID].assistant != "" || record.UUID == "" {
					return nil
				}
				tools[block.ID] = claudeInputTool{assistant: record.UUID, name: block.Name}
				command, _ := block.Input["command"].(string)
				if block.Name == "Bash" && matchesClaudeCapability(command, capability, request) {
					if selected != nil || latest == nil {
						return nil
					}
					selected, selectedTool = latest, block.ID
				}
			}
		} else {
			if selectedTool != "" && slices.ContainsFunc(blocks, func(block claudeInterruptedBlock) bool {
				return block.Type == "tool_result" && block.ToolUseID == selectedTool
			}) {
				return nil
			}
			if selected == nil && slices.ContainsFunc(blocks, func(block claudeInterruptedBlock) bool {
				return block.Type == "tool_result"
			}) {
				content, fingerprint := claudeInputResult(record, tools)
				if content == nil {
					return nil
				}
				batch.add(content, fingerprint, len(record.Message.Content))
				if fingerprint.message != "" {
					observed = append(observed, fingerprint)
					if len(observed) > claudeInputProofLimit {
						return nil
					}
				}
			}
		}
	}
	if selected == nil || selected != latest {
		return nil
	}
	result := &ClaudeModelInputEvidence{ProviderID: binding.ProviderID, PromptID: turn, RequestSHA256: selected.digest, Capabilities: []ClaudeInputRead{}, Images: []ClaudeInputImage{}}
	included := selected.messageHashes()
	seenReads := make(map[ClaudeInputRead]bool)
	seenImages := make(map[ClaudeInputImage]bool)
	for _, fingerprint := range observed {
		if !included[fingerprint.message] {
			continue
		}
		for _, capability := range fingerprint.capabilities {
			if !seenReads[capability] {
				result.Capabilities = append(result.Capabilities, capability)
				seenReads[capability] = true
			}
		}
		for _, image := range fingerprint.images {
			if !seenImages[image] {
				result.Images = append(result.Images, image)
				seenImages[image] = true
			}
		}
	}
	if len(result.Capabilities)+len(result.Images) == 0 || len(result.Capabilities)+len(result.Images) > claudeInputProofLimit {
		return nil
	}
	return result
}

func matchesClaudeCapability(command, capability, request string) bool {
	match := claudeCapabilityCommand.FindStringSubmatch(command)
	return len(match) > 2 && match[1] == capability && slices.Contains(match[2:], request)
}

func claudeModelRequest(record claudeModelInputRecord, requests map[string]*claudeRequestDelta, provider string) *claudeRequestDelta {
	base := requests[record.Base]
	if record.SessionID != provider || record.RequestID == "" || requests[record.RequestID] != nil ||
		!claudeRequestSHA.MatchString(record.RequestDigest) || record.Keep == nil || *record.Keep < 0 ||
		record.Tail == nil || len(record.Tail) > 4096 || len(requests) >= 8192 ||
		base == nil && (record.Base != "" || *record.Keep != 0) ||
		base != nil && *record.Keep > base.length || *record.Keep+len(record.Tail) > 4096 {
		return nil
	}
	for _, hash := range record.Tail {
		if !claudeRequestSHA.MatchString(hash) {
			return nil
		}
	}
	return &claudeRequestDelta{base: base, keep: *record.Keep, tail: record.Tail, length: *record.Keep + len(record.Tail), digest: record.RequestDigest}
}

func claudeInputDirectory(binding SessionBinding, cwd string) bool {
	if cwd == binding.Directory {
		return true
	}
	_, ok := reportDirectory(binding.Directory, cwd)
	return ok
}

func claudeInputResult(record claudeModelInputRecord, tools map[string]claudeInputTool) ([]map[string]any, claudeInputFingerprint) {
	decoder := json.NewDecoder(bytes.NewReader(record.Message.Content))
	decoder.UseNumber()
	var blocks []map[string]any
	if decoder.Decode(&blocks) != nil {
		return nil, claudeInputFingerprint{}
	}
	var result claudeInputFingerprint
	for _, block := range blocks {
		id, _ := block["tool_use_id"].(string)
		source, tracked := tools[id]
		if !tracked || block["type"] != "tool_result" || block["is_error"] == true ||
			record.SourceAssistant != source.assistant || record.Parent != source.assistant {
			continue
		}
		switch source.name {
		case "Bash":
			stdout, _ := block["content"].(string)
			if read := claudeCapabilityReceipt(stdout); read.ToolCallID != "" {
				result.capabilities = append(result.capabilities, read)
			}
		case "Read":
			items, _ := block["content"].([]any)
			for _, entry := range items {
				item, _ := entry.(map[string]any)
				image, _ := item["source"].(map[string]any)
				if item["type"] != "image" || image["type"] != "base64" {
					continue
				}
				mime, _ := image["media_type"].(string)
				data, _ := image["data"].(string)
				if !slices.Contains([]string{"image/png", "image/jpeg", "image/gif", "image/webp"}, mime) || data == "" {
					continue
				}
				if raw, err := base64.StdEncoding.Strict().DecodeString(data); err == nil {
					result.images = append(result.images, ClaudeInputImage{MIME: mime, SHA256: workspaceHash(string(raw))})
				}
			}
		}
	}
	if len(result.capabilities)+len(result.images) > 0 {
		result.message = claudeInputDigest(map[string]any{"role": "user", "content": blocks})
	}
	return blocks, result
}

func claudeCapabilityReceipt(stdout string) ClaudeInputRead {
	decoder := json.NewDecoder(strings.NewReader(stdout))
	decoder.UseNumber()
	var envelope map[string]any
	if decoder.Decode(&envelope) != nil || len(envelope) != 1 || decoder.Decode(new(any)) != io.EOF {
		return ClaudeInputRead{}
	}
	data, _ := envelope["data"].(map[string]any)
	id, _ := data["toolCallId"].(string)
	if len(data) != 5 || !claudeCapabilityID.MatchString(id) || data["state"] != "succeeded" ||
		data["result"] == nil || data["requestId"] == nil || data["finishedMs"] == nil {
		return ClaudeInputRead{}
	}
	return ClaudeInputRead{ToolCallID: id, ResponseSHA256: claudeInputDigest(envelope)}
}

func claudeInputDigest(value any) string {
	var canonical bytes.Buffer
	encoder := json.NewEncoder(&canonical)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return ""
	}
	return workspaceHash(strings.TrimSuffix(canonical.String(), "\n"))
}
