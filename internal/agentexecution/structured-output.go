package agentexecution

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strings"
)

func structuredExecutor(kind string) bool { return kind == "opencode" || kind == "pi" }

// Consume LF-delimited native events; Unicode separators inside JSON strings are data.
type structuredOutput struct {
	kind, provider            string
	pending                   []byte
	text                      tail
	complete, failed, invalid bool
	finalStop                 bool
	tools                     map[string]bool
}

func newStructuredOutput(kind, provider string) *structuredOutput {
	return &structuredOutput{kind: kind, provider: provider, text: tail{limit: 32000}, tools: map[string]bool{}}
}

func (p *structuredOutput) Write(data []byte) (int, error) {
	p.pending = append(p.pending, data...)
	for {
		i := bytes.IndexByte(p.pending, '\n')
		if i < 0 {
			break
		}
		if i > 4*1024*1024 {
			p.invalid = true
		} else {
			p.consume(p.pending[:i])
		}
		p.pending = p.pending[i+1:]
	}
	if len(p.pending) > 4*1024*1024 {
		p.invalid = true
		p.pending = nil
	}
	return len(data), nil
}

func (p *structuredOutput) finish() {
	if len(bytes.TrimSpace(p.pending)) != 0 {
		p.consume(p.pending)
	}
	p.pending = nil
}
func (p *structuredOutput) bind(id string) {
	if id == "" || len(id) > 300 || strings.ContainsAny(id, "\x00\r\n") {
		p.invalid = true
		return
	}
	if p.provider != "" && id != p.provider {
		p.invalid = true
		return
	}
	p.provider = id
}
func (p *structuredOutput) consume(line []byte) {
	if len(bytes.TrimSpace(line)) == 0 {
		return
	}
	var e struct {
		Type      string `json:"type"`
		ID        string `json:"id"`
		SessionID string `json:"sessionID"`
		ToolID    string `json:"toolCallId"`
		Aborted   *bool  `json:"aborted"`
		Part      struct {
			Text   string `json:"text"`
			Reason string `json:"reason"`
		} `json:"part"`
		Message struct {
			Role       string          `json:"role"`
			StopReason string          `json:"stopReason"`
			Content    json.RawMessage `json:"content"`
		} `json:"message"`
	}
	if json.Unmarshal(line, &e) != nil {
		p.invalid = true
		return
	}
	if p.kind == "opencode" {
		p.bind(e.SessionID)
		switch e.Type {
		case "text":
			p.text.Write([]byte(e.Part.Text + "\n"))
		case "step_start", "tool_use":
			p.complete = false
		case "step_finish":
			p.complete = e.Part.Reason == "stop" || e.Part.Reason == "end_turn"
		case "error":
			p.failed = true
			p.complete = false
		}
		return
	}
	switch e.Type {
	case "session":
		p.bind(e.ID)
	case "agent_start":
		p.complete = false
	case "tool_execution_start":
		p.tools[e.ToolID] = true
		p.complete = false
	case "tool_execution_end":
		delete(p.tools, e.ToolID)
	case "message_end":
		if e.Message.Role != "assistant" {
			return
		}
		p.failed = e.Message.StopReason == "error" || e.Message.StopReason == "aborted"
		p.finalStop = e.Message.StopReason == "stop"
		// The last assistant message, rather than deltas or intermediate tool commentary, is the handoff.
		p.text.data = nil
		var content []struct {
			Type string `json:"type"`
			Text string `json:"text"`
		}
		if json.Unmarshal(e.Message.Content, &content) != nil {
			p.invalid = true
			return
		}
		for _, c := range content {
			if c.Type == "text" {
				p.text.Write([]byte(c.Text + "\n"))
			}
		}
	case "agent_settled":
		p.complete = e.Aborted != nil && !*e.Aborted && p.finalStop
		p.failed = p.failed || (e.Aborted != nil && *e.Aborted)
	}
}
func (p *structuredOutput) validate() error {
	if p.invalid || p.provider == "" {
		return fmt.Errorf("INVALID_EXECUTOR_EVENT_STREAM")
	}
	if p.failed {
		return fmt.Errorf("EXECUTOR_REPORTED_FAILURE")
	}
	if !p.complete || len(p.tools) != 0 || strings.TrimSpace(p.text.String()) == "" {
		return fmt.Errorf("EXECUTOR_COMPLETION_UNCONFIRMED")
	}
	return nil
}
