package protocol

import (
	"bytes"
	"encoding/json"
)

// RequestUsesImages inspects message and tool output blocks without interpreting tool arguments.
func RequestUsesImages(payload map[string]json.RawMessage, protocol string) bool {
	input := payload["messages"]
	if protocol == "openai-responses" {
		input = payload["input"]
	}
	var messages []struct {
		Type    string          `json:"type"`
		Content json.RawMessage `json:"content"`
		Output  json.RawMessage `json:"output"`
	}
	if input = bytes.TrimSpace(input); len(input) == 0 || input[0] != '[' || json.Unmarshal(input, &messages) != nil {
		return false
	}
	for _, message := range messages {
		if (protocol == "openai-responses" && message.Type == "input_image") ||
			imageContent(message.Content, protocol == "anthropic-messages") ||
			(message.Type == "function_call_output" && imageContent(message.Output, false)) {
			return true
		}
	}
	return false
}

func imageContent(raw json.RawMessage, includeToolResult bool) bool {
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 || raw[0] != '[' {
		return false
	}
	var blocks []struct {
		Type    string          `json:"type"`
		Content json.RawMessage `json:"content"`
	}
	if json.Unmarshal(raw, &blocks) != nil {
		return false
	}
	for _, block := range blocks {
		switch block.Type {
		case "image", "input_image", "image_url":
			return true
		case "tool_result":
			if includeToolResult && imageContent(block.Content, false) {
				return true
			}
		}
	}
	return false
}
