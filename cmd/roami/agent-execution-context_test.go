package main

import "testing"

func TestAgentExecutionContextDoesNotAcceptCallerIdentity(t *testing.T) {
	for _, args := range [][]string{
		{"context", "--caller-pid", "1"},
		{"context", "--pane", "%1"},
		{"context", "--key", "another-launch"},
		{"context", "--executor", "codex"},
		{"context", "another-session"},
	} {
		t.Run(args[1], func(t *testing.T) {
			if code := runAgentExecution(args); code != 2 {
				t.Fatalf("caller-supplied identity accepted: %v: %d", args, code)
			}
		})
	}
}

func TestAgentExecutionContextHelpDoesNotQueryTheSession(t *testing.T) {
	t.Setenv("TMUX_PANE", "")
	if code := runAgentExecution([]string{"context", "--help"}); code != 0 {
		t.Fatalf("read-only help required an execution context: %d", code)
	}
}
