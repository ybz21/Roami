package api

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestPiProviderSelectionNeverFallsBackToAnotherSameDirectoryInstance(t *testing.T) {
	root := t.TempDir()
	dir := "/project"
	project := filepath.Join(root, "--project--")
	if err := os.Mkdir(project, 0700); err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	write := func(id string, created time.Time) string {
		file := filepath.Join(project, "2026-11-06_"+id+".jsonl")
		header, _ := json.Marshal(piEntry{Type: "session", ID: id, Cwd: dir, Timestamp: created.Format(time.RFC3339Nano)})
		if err := os.WriteFile(file, append(header, '\n'), 0600); err != nil {
			t.Fatal(err)
		}
		return file
	}
	original := write("original", now.Add(-time.Hour))
	newer := write("newer", now)
	for _, flag := range []string{"--session-id", "--session"} {
		if got := pickPiTranscript(root, dir, []string{"pi", flag, "original"}, now); got != original {
			t.Fatalf("%s selected %q", flag, got)
		}
		for _, absent := range []string{"missing", "orig"} {
			if got := pickPiTranscript(root, dir, []string{"pi", flag, absent}, now); got != "" {
				t.Fatalf("missing/partial id selected %q", got)
			}
		}
	}
	if got := pickPiTranscript(root, dir, []string{"pi"}, now); got != newer {
		t.Fatalf("new process selected %q", got)
	}
	write("another", now)
	if got := pickPiTranscript(root, dir, []string{"pi"}, now); got != "" {
		t.Fatalf("ambiguous process selected %q", got)
	}
	if got := pickPiTranscript(root, dir, []string{"pi", "--session", original}, now); got != original {
		t.Fatal("exact resume file lost")
	}
	if got := pickPiTranscript(root, dir, []string{"pi", "--session", "/etc/passwd"}, now); got != "" {
		t.Fatal("foreign file accepted")
	}
	if err := os.Symlink(original, filepath.Join(project, "escape.jsonl")); err != nil {
		t.Fatal(err)
	}
	if got := pickPiTranscript(root, dir, []string{"pi", "--session-id", "original", "--no-session"}, now); got != "" {
		t.Fatal("disabled session inherited a transcript")
	}
}

func TestPiBranchProjectionKeepsOnlyTheCurrentParentChainAndPairsTools(t *testing.T) {
	text := `{"type":"session","version":3,"id":"session","cwd":"/project"}
{"type":"message","id":"u1","parentId":null,"timestamp":"2026-11-06T09:00:00Z","message":{"role":"user","content":"Start"}}
{"type":"message","id":"old","parentId":"u1","message":{"role":"assistant","content":[{"type":"text","text":"Abandoned branch"}]}}
{"type":"message","id":"a2","parentId":"u1","message":{"role":"assistant","model":"pi-model","content":[{"type":"thinking","thinking":"Consider"},{"type":"toolCall","id":"call","name":"read","arguments":{"path":"AGENTS.md"}}]}}
{"type":"message","id":"r2","parentId":"a2","message":{"role":"toolResult","toolCallId":"call","isError":true,"content":[{"type":"text","text":"Missing"}]}}
{"type":"message","id":"a3","parentId":"r2","message":{"role":"assistant","content":[{"type":"text","text":"Done"}]}}
`
	messages, status, more := piBranch(splitLines([]byte(text), 0), 200)
	if len(messages) != 4 || more || status.Model != "pi-model" {
		t.Fatalf("unexpected branch: %+v %+v %v", messages, status, more)
	}
	if messages[1].ID != "a2" || messages[1].Blocks[0].Kind != "thinking" || messages[1].Blocks[1].ID != "call" || messages[1].Blocks[1].Input != `{"path":"AGENTS.md"}` {
		t.Fatalf("assistant/tool call lost: %+v", messages[1])
	}
	if messages[2].Role != "tool" || messages[2].Blocks[0].ToolUseID != "call" || !messages[2].Blocks[0].IsError {
		t.Fatalf("tool result lost: %+v", messages[2])
	}
	last, _, more := piBranch(splitLines([]byte(text), 0), 2)
	if len(last) != 2 || last[0].ID != "r2" || !more {
		t.Fatal("window does not retain the current branch tail")
	}
	cut := strings.Index(text, `{"type":"message","id":"a2"`)
	last, _, more = piBranch(splitLines([]byte(text[cut:]), int64(cut)), 200)
	if len(last) != 3 || !more {
		t.Fatal("missing ancestor was not marked for earlier loading")
	}
	partial := text + `{"type":"message","id":"partial","parentId":"a3","message":`
	last, _, _ = piBranch(splitLines([]byte(partial), 0), 200)
	if len(last) != 4 || last[3].ID != "a3" {
		t.Fatal("partial JSON tail displaced the last complete message")
	}
}
