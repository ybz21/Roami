package main

import (
	agentcommands "github.com/ybz21/Roami/agent-runtime"
	"slices"
	"testing"
)

func TestNamedOperationsUseAdmittedLegacyTransport(t *testing.T) {
	for name, path := range agentcommands.Paths() {
		got, input, matched := boundCommand(append(slices.Clone(path), "--input", `{"query":"fixture"}`))
		if !matched || got != name || input != `{"query":"fixture"}` {
			t.Fatalf("%s: %s %s %v", name, got, input, matched)
		}
	}
	for _, args := range [][]string{{"agent", "memory", "search", "--input"}, {"agent", "task", "cancel", "--input", "{", "extra"}} {
		name, _, matched := boundCommand(args)
		if !matched || name != "" {
			t.Fatalf("invalid command accepted: %v", args)
		}
	}
	if _, _, matched := boundCommand([]string{"session", "send", "session-id", "text"}); matched {
		t.Fatal("ordinary session send was intercepted")
	}
}
