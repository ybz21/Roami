package agentexecution

import (
	"strings"
	"testing"
)

func TestAntigravityRequiresExactConversationAndACompleteResult(t *testing.T) {
	const id = "a1b2c3d4-1234-5678-9abc-0123456789ab"
	const other = "b1b2c3d4-1234-5678-9abc-0123456789ab"
	const init = `{"event":"init","conversation_id":"` + id + `"}`
	const step = `{"event":"step_update","step_update":{"conversation_id":"` + id + `","text_delta":"interim"}}`
	const done = `{"event":"result","result":{"conversation_id":"` + id + `","status":"SUCCESS","response":"final"}}`
	for _, tc := range []struct {
		name   string
		events []string
		ok     bool
	}{
		{"complete", []string{init, step, done}, true},
		{"missing init", []string{done}, false},
		{"partial", []string{init, step}, false},
		{"unexpected conversation", []string{init, strings.ReplaceAll(done, id, other)}, false},
		{"mismatched step", []string{init, strings.ReplaceAll(step, id, other), done}, false},
		{"failure", []string{init, strings.ReplaceAll(done, "SUCCESS", "ERROR")}, false},
		{"timeout", []string{init, strings.ReplaceAll(done, `"response"`, `"finished_reason":"print_timeout","response"`)}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			parser := newStructuredOutput("antigravity", id)
			parser.Write([]byte(strings.Join(tc.events, "\n")))
			parser.finish()
			err := parser.validate()
			if (err == nil) != tc.ok || tc.ok && parser.text.String() != "final" {
				t.Fatalf("summary = %q, error = %v", parser.text.String(), err)
			}
		})
	}
}
