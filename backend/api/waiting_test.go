package api

import (
	"strings"
	"testing"
)

func TestSessionWaitingRejectsAgentCommandList(t *testing.T) {
	capture := `Running implementation work…
  1. Run the formatter command
  2. Continue with the typecheck
  3. Write the result > report.txt
Working…`
	if sessionWaiting(capture) {
		t.Fatal("normal agent command list must not be treated as waiting for confirmation")
	}
}

func TestSessionWaitingRejectsQuotedListAndHistoricalYesNo(t *testing.T) {
	capture := `Documentation example:
> 1. Run the command
> 2. Continue editing
Answer prompts with (y/n).
Done.`
	if sessionWaiting(capture) {
		t.Fatal("quoted list or historical y/n text must not be treated as a current prompt")
	}
}

func TestSessionWaitingAcceptsCursorMenu(t *testing.T) {
	capture := `Select model
  1. Default
❯ 2. Opus
  3. Fable
Enter to select · Esc to cancel`
	if !sessionWaiting(capture) {
		t.Fatal("menu with an option cursor must be treated as waiting for confirmation")
	}
}

func TestSessionWaitingAcceptsExplicitPromptWithoutCursor(t *testing.T) {
	capture := `Are you sure you want to proceed?
  1. Yes, continue
  2. No, go back
Enter to confirm · Esc to cancel`
	if !sessionWaiting(capture) {
		t.Fatal("explicit question with action hints must be treated as waiting for confirmation")
	}
}

func TestSessionWaitingRejectsNumberedCodexComposer(t *testing.T) {
	capture := `Worked for 56m 58s
› 1. 手机支持下拉刷新页面
  2. 下载 App 要有能够感知到的地方
GPT-6-Sol medium · ← for agents · ? for shortcuts`
	if sessionWaiting(capture) {
		t.Fatal("numbered task text in the Codex composer is not a choice menu")
	}
}

func TestScreenBusyAgentStatus(t *testing.T) {
	cases := []struct {
		name    string
		capture string
		busy    bool
	}{
		{"pi working", "── ⠸ Working ──────────\n~/codes/project\n↑46k ↓18k", true},
		{"pi idle", "Result delivered\n~/codes/project\n↑46k ↓18k", false},
		{"opencode running", "Output in progress\nesc interrupt\n", true},
		{"opencode interrupt armed", "Output in progress\nesc again to interrupt\n", true},
		{"opencode idle", "Output complete\n~/codes/project\n", false},
		{"historical opencode status", "esc interrupt\n" + strings.Repeat("new output\n", 12), false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := screenBusy(tc.capture); got != tc.busy {
				t.Errorf("screenBusy() = %v, want %v", got, tc.busy)
			}
		})
	}
}
