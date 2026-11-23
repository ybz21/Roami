package agentexecution

import (
	"strings"
	"testing"
)

func TestGeminiRequiresNativeCompletionAndExactConversation(t *testing.T) {
	const session = "a1b2c3d4-1234-5678-9abc-0123456789ab"
	const init = `{"type":"init","session_id":"` + session + `"}`
	const message = `{"type":"message","role":"assistant","content":"final","delta":true}`
	const success = `{"type":"result","status":"success"}`
	const toolUse = `{"type":"tool_use","tool_id":"tool-1"}`
	const toolResult = `{"type":"tool_result","tool_id":"tool-1","status":"success"}`
	for _, tc := range []struct {
		name   string
		events []string
		answer string
	}{
		{"answer", []string{init, message, success}, "final"},
		{"tool round", []string{init, message, toolUse, toolResult, message, message, success}, "finalfinal"},
		{"user echo", []string{init, `{"type":"message","role":"user","content":"final"}`, success}, ""},
		{"unfinished tool", []string{init, toolUse, message, success}, ""},
		{"missing result", []string{init, message}, ""},
		{"missing init on resume", []string{message, success}, ""},
		{"different session", []string{`{"type":"init","session_id":"21234567-1234-5678-9abc-0123456789ab"}`, message, success}, ""},
		{"provider failure", []string{init, message, `{"type":"result","status":"error"}`}, ""},
		{"content after result", []string{init, message, success, message}, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			parser := newStructuredOutput("gemini", session)
			parser.Write([]byte(strings.Join(tc.events, "\n")))
			parser.finish()
			err := parser.validate()
			if tc.answer == "" {
				if err == nil {
					t.Fatal("invalid or incomplete stream was accepted")
				}
				return
			}
			if err != nil || parser.text.String() != tc.answer {
				t.Fatalf("summary = %q, error = %v", parser.text.String(), err)
			}
		})
	}
}
