package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestSessionEventInputAcceptsLargeReadCallbackWithoutChangingOrdinaryCLIInput(t *testing.T) {
	path := filepath.Join(t.TempDir(), "hook.json")
	body := `{"hook_event_name":"PostToolUse","session_id":"provider","prompt_id":"prompt","tool_use_id":"read","tool_response":"` + strings.Repeat("x", 200000) + `"}`
	if err := os.WriteFile(path, []byte(body), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := agentInput(path, ""); err == nil {
		t.Fatal("ordinary CLI input contract changed")
	}
	event, err := sessionEventInput(path, "")
	if err != nil || event.ToolID != "read" {
		t.Fatalf("hook incorrectly used the ordinary CLI cap: %+v %v", event, err)
	}
}
