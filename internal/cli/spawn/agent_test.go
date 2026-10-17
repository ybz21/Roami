package spawn

import "testing"

func TestClaudeOneShot(t *testing.T) {
	ac := AgentConfig{ClaudeBin: "claude", Kind: "claude", Permission: "dangerously-skip-permissions", Workdir: "/work"}
	got := ac.Command("do the thing")
	want := "cd '/work' && claude -p --dangerously-skip-permissions --output-format text <<'TTMUX_TASK_EOF'\ndo the thing\nTTMUX_TASK_EOF"
	if got != want {
		t.Fatalf("claude one-shot mismatch:\n got=%q\nwant=%q", got, want)
	}
}

func TestClaudeInteractiveWithModelAndPerm(t *testing.T) {
	ac := AgentConfig{ClaudeBin: "claude", Kind: "claude", Interactive: true, Permission: "auto", Model: "opus", Workdir: "/w"}
	got := ac.Command("hi")
	want := "cd '/w' && claude --model opus --permission-mode auto 'hi'"
	if got != want {
		t.Fatalf("claude interactive mismatch:\n got=%q\nwant=%q", got, want)
	}
}

func TestCodexOneShot(t *testing.T) {
	ac := AgentConfig{CodexBin: "codex", Kind: "codex", Permission: "dangerously-skip-permissions", Workdir: "/w"}
	got := ac.Command("task")
	want := "cd '/w' && codex exec --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox - <<'TTMUX_TASK_EOF'\ntask\nTTMUX_TASK_EOF"
	if got != want {
		t.Fatalf("codex one-shot mismatch:\n got=%q\nwant=%q", got, want)
	}
}

func TestCodexInteractive(t *testing.T) {
	ac := AgentConfig{CodexBin: "codex", Kind: "codex", Interactive: true, Model: "gpt", Workdir: "/w"}
	got := ac.Command("go")
	want := "cd '/w' && codex -m gpt 'go'"
	if got != want {
		t.Fatalf("codex interactive mismatch:\n got=%q\nwant=%q", got, want)
	}
}

func TestShellQuoteEscapesSingleQuote(t *testing.T) {
	if got := shellQuote("a'b"); got != `'a'\''b'` {
		t.Fatalf("shellQuote mismatch: %q", got)
	}
}
