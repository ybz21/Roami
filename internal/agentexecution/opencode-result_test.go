package agentexecution

import (
	"encoding/json"
	"path/filepath"
	"testing"
)

func TestOpenCodeExportBindsNewPromptAndCompletedTurn(t *testing.T) {
	dir := t.TempDir()
	seed := func() map[string]any {
		return map[string]any{
			"info": map[string]any{"id": "ses_test", "outcome": "succeeded", "location": map[string]any{"directory": dir}},
			"messages": []any{
				map[string]any{"type": "user", "text": "original prompt", "time": map[string]any{"created": int64(101)}},
				map[string]any{"type": "assistant", "finish": "stop", "time": map[string]any{"completed": int64(102)}, "content": []any{map[string]any{"type": "text", "text": "Verified handoff"}}},
				map[string]any{"type": "idle", "outcome": "succeeded"},
			},
		}
	}
	for _, name := range []string{"valid", "wrong session", "wrong directory", "wrong prompt", "old identical prompt", "failed session", "running tool", "incomplete assistant", "no idle", "last user has no answer"} {
		t.Run(name, func(t *testing.T) {
			x := seed()
			info := x["info"].(map[string]any)
			messages := x["messages"].([]any)
			assistant := messages[1].(map[string]any)
			switch name {
			case "wrong session":
				info["id"] = "ses_other"
			case "wrong directory":
				info["location"] = map[string]any{"directory": filepath.Dir(dir)}
			case "wrong prompt":
				messages[0].(map[string]any)["text"] = "different"
			case "old identical prompt":
				messages[0].(map[string]any)["time"] = map[string]any{"created": int64(99)}
			case "failed session":
				info["outcome"] = "failed"
			case "running tool":
				assistant["content"] = []any{map[string]any{"type": "tool", "state": map[string]any{"status": "running"}}}
			case "incomplete assistant":
				assistant["finish"] = "tool-calls"
			case "no idle":
				x["messages"] = messages[:2]
			case "last user has no answer":
				x["messages"] = append(messages, map[string]any{"type": "user", "text": "original prompt", "time": map[string]any{"created": int64(103)}})
			}
			data, _ := json.Marshal(x)
			text, err := readOpenCodeResult(data, "ses_test", dir, "original prompt", 100)
			if name == "valid" {
				if err != nil || text != "Verified handoff" {
					t.Fatal(text, err)
				}
			} else if err == nil {
				t.Fatal("accepted unbound completion")
			}
		})
	}
}

func TestPiNativeSystemMessagesAndRecoveredRetry(t *testing.T) {
	p := newStructuredOutput("pi", "p1")
	p.Write([]byte(`{"type":"session","id":"p1"}
{"type":"message_end","message":{"role":"system","content":"Native system context"}}
{"type":"message_end","message":{"role":"user","content":"Original prompt"}}
{"type":"message_end","message":{"role":"assistant","stopReason":"error","content":[]}}
{"type":"agent_start"}
{"type":"message_end","message":{"role":"assistant","stopReason":"stop","content":[{"type":"text","text":"Recovered"}]}}
{"type":"agent_settled","aborted":false}
`))
	p.finish()
	if p.validate() != nil {
		t.Fatal(p.validate())
	}
}
