package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/internal/agentexecution"
)

func TestExecutionInputPreservesLongConversationWithoutChangingOrdinaryInput(t *testing.T) {
	prompt := strings.Repeat("原 Main 的历史与工具记录\n", 12000)
	body, err := json.Marshal(agentexecution.Spec{Key: "same-turn", Executor: "claude", SessionID: "existing", PreparedFrom: "prepared", Persistent: true, Prompt: prompt})
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "execution.json")
	if err := os.WriteFile(path, body, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := agentInput(path, ""); err == nil {
		t.Fatal("ordinary CLI input limit was relaxed")
	}
	for _, source := range []string{path, "-"} {
		t.Run(source, func(t *testing.T) {
			if source == "-" {
				input, err := os.Open(path)
				if err != nil {
					t.Fatal(err)
				}
				defer input.Close()
				previous := os.Stdin
				os.Stdin = input
				defer func() { os.Stdin = previous }()
			}
			content, err := executionSpecInput(source)
			if err != nil {
				t.Fatal(err)
			}
			var spec agentexecution.Spec
			if err := json.Unmarshal(content, &spec); err != nil {
				t.Fatal(err)
			}
			if spec.Prompt != prompt || spec.SessionID != "existing" || spec.PreparedFrom != "prepared" {
				t.Fatal("conversation or original provider identity was truncated")
			}
		})
	}
}

func TestExecutionInputStillRejectsOversizeRequests(t *testing.T) {
	path := filepath.Join(t.TempDir(), "oversize.json")
	if err := os.WriteFile(path, []byte(strings.Repeat("x", (8<<20)+1)), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := executionSpecInput(path); err == nil || err.Error() != "AGENT_INPUT_TOO_LARGE" {
		t.Fatalf("oversize request was not rejected: %v", err)
	}
}
