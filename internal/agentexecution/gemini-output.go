package agentexecution

import (
	"encoding/json"

	"github.com/ybz21/Roami/internal/agent"
)

func (p *structuredOutput) consumeGemini(line []byte) {
	var event struct {
		Type      string `json:"type"`
		SessionID string `json:"session_id"`
		Role      string `json:"role"`
		Content   string `json:"content"`
		ToolID    string `json:"tool_id"`
		Status    string `json:"status"`
		Severity  string `json:"severity"`
	}
	if json.Unmarshal(line, &event) != nil || event.Type == "" || p.complete {
		p.invalid = true
		return
	}
	// Authentication and startup errors can arrive before Gemini opens a conversation.
	if event.Type == "error" {
		p.failed = p.failed || event.Severity != "warning"
		return
	}
	if event.Type == "init" {
		if p.initialized || !agent.ValidGeminiSessionID(event.SessionID) {
			p.invalid = true
			return
		}
		p.bind(event.SessionID)
		p.initialized = true
		return
	}
	if !p.initialized {
		p.invalid = true
		return
	}
	switch event.Type {
	case "message":
		if event.Role == "assistant" {
			p.text.Write([]byte(event.Content))
		}
	case "tool_use":
		if event.ToolID == "" || p.tools[event.ToolID] {
			p.invalid = true
			return
		}
		p.tools[event.ToolID] = true
		// A later assistant answer supersedes the text emitted before a tool call.
		p.text.data = nil
	case "tool_result":
		if !p.tools[event.ToolID] {
			p.invalid = true
			return
		}
		delete(p.tools, event.ToolID)
	case "result":
		p.complete = event.Status == "success"
		p.failed = p.failed || !p.complete
	}
}
