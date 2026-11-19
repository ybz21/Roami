package agentexecution

import (
	"encoding/json"
	"strings"
	"time"
)

// A provider report is diagnostic evidence, never input-stop or business-outcome proof.
type ReportedToolError struct {
	Source       string `json:"source"`
	Code         string `json:"code"`
	Tool         string `json:"tool"`
	ToolUseID    string `json:"toolUseId"`
	Directory    string `json:"directory"`
	ProviderID   string `json:"providerConversationId"`
	PromptID     string `json:"promptId"`
	SourceDigest string `json:"sourceDigest"`
	ObservedMS   int64  `json:"observedMs"`
}

type claudeToolErrorState struct {
	discarded bool
	tools     map[string]string
	report    *ReportedToolError
}

func classifierUnavailable(text, tool string) bool {
	model, rest, found := strings.Cut(text, " is temporarily unavailable (timed out), so auto mode cannot determine the safety of ")
	return found && model != "" && len(model) <= 256 && !strings.ContainsAny(model, " \r\n\t") && strings.HasPrefix(rest, tool+" right now. Wait a moment and then try this action again.")
}

func (s *claudeToolErrorState) observe(binding SessionBinding, turn string, record claudeReportRecord) {
	if s.discarded {
		return
	}
	var blocks []struct {
		Type      string          `json:"type"`
		ID        string          `json:"id"`
		Name      string          `json:"name"`
		ToolUseID string          `json:"tool_use_id"`
		IsError   bool            `json:"is_error"`
		Content   json.RawMessage `json:"content"`
	}
	if json.Unmarshal(record.Message.Content, &blocks) != nil {
		return
	}
	directory, ok := reportDirectory(binding.Directory, record.Cwd)
	if !ok {
		return
	}
	for _, block := range blocks {
		if record.Type == "assistant" && block.Type == "tool_use" && block.ID != "" && len(block.ID) <= 256 && block.Name != "" && len(block.Name) <= 256 {
			s.tools[block.ID] = block.Name
			continue
		}
		if record.Type != "user" || block.Type != "tool_result" {
			continue
		}
		tool := s.tools[block.ToolUseID]
		delete(s.tools, block.ToolUseID)
		var text string
		if tool == "" || !block.IsError || json.Unmarshal(block.Content, &text) != nil || !classifierUnavailable(text, tool) {
			continue
		}
		stamp, err := time.Parse(time.RFC3339Nano, record.Timestamp)
		if err != nil || stamp.UnixMilli() <= 0 {
			continue
		}
		report := &ReportedToolError{Source: "provider_transcript", Code: "CLAUDE_AUTO_CLASSIFIER_UNAVAILABLE", Tool: tool, ToolUseID: block.ToolUseID, Directory: directory, ProviderID: binding.ProviderID, PromptID: turn, ObservedMS: stamp.UnixMilli()}
		proof, _ := json.Marshal(struct {
			Report        *ReportedToolError
			ContentSHA256 string
		}{report, workspaceHash(text)})
		report.SourceDigest = workspaceHash(string(proof))
		s.report = report
	}
}
