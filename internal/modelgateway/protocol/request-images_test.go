package protocol

import (
	"encoding/json"
	"testing"
)

func TestRequestUsesImagesInWireContent(t *testing.T) {
	tests := []struct {
		name, protocol, request string
		want                    bool
	}{
		{"anthropic tool output", "anthropic-messages", `{"messages":[{"role":"user","content":[{"type":"tool_result","content":[{"type":"image"}]}]}]}`, true},
		{"anthropic tool argument", "anthropic-messages", `{"messages":[{"role":"assistant","content":[{"type":"tool_use","input":{"type":"image"}}]}]}`, false},
		{"chat message", "openai-completions", `{"messages":[{"role":"user","content":[{"type":"image_url"}]}]}`, true},
		{"responses message", "openai-responses", `{"input":[{"type":"message","content":[{"type":"input_image"}]}]}`, true},
		{"responses tool output", "openai-responses", `{"input":[{"type":"function_call_output","output":[{"type":"input_image"}]}]}`, true},
		{"plain text", "openai-completions", `{"messages":[{"content":"type: image"}]}`, false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			var payload map[string]json.RawMessage
			if err := json.Unmarshal([]byte(test.request), &payload); err != nil {
				t.Fatal(err)
			}
			if got := RequestUsesImages(payload, test.protocol); got != test.want {
				t.Fatalf("images=%v, want %v", got, test.want)
			}
		})
	}
}
