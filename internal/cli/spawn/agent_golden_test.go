package spawn

import "testing"

// 启动命令的**逐字基线**。
//
// 这些命令最终由 tmux send-keys 敲进 pane，一个字符不对就是 agent 起不来
// 或者起错档（比如少了 --dangerously-skip-permissions 会卡在交互确认上，
// 而那是无人值守的会话，没人去按）。所以这里断言全串相等，不做模糊匹配。
//
// 它同时是把「每型自己的参数」下放到 internal/agent 那次重构的安全网：
// 外壳（cd / 引号 / heredoc / bin 覆盖）留在本包，参数由各型自述，
// 两边加起来必须和重构前逐字一样。
func TestLaunchCommandGolden(t *testing.T) {
	cases := []struct {
		name string
		ac   AgentConfig
		// 三种投喂方式各有各的用途：内联 heredoc（短任务）、文件走 stdin
		// （send-keys 有长度上限，大 prompt 必须走这条）、$(cat) 注入（交互式 TUI）。
		wantCommand string
		wantFromFn  string
		wantInterFn string
	}{
		{
			name: "claude/一次性/跳过权限/带 max-turns",
			ac:   AgentConfig{ClaudeBin: "claude", Kind: "claude", Permission: "dangerously-skip-permissions", Workdir: "/w", MaxTurns: "5"},
			wantCommand: "cd '/w' && claude -p --dangerously-skip-permissions --max-turns 5 --output-format text " +
				"<<'TTMUX_TASK_EOF'\nT\nTTMUX_TASK_EOF",
			wantFromFn:  "cd '/w' && claude -p --dangerously-skip-permissions --max-turns 5 --output-format text < '/p.txt'",
			wantInterFn: "cd '/w' && claude --dangerously-skip-permissions \"$(cat '/p.txt')\"",
		},
		{
			name:        "claude/交互/模型+权限档/带对话 id",
			ac:          AgentConfig{ClaudeBin: "claude", Kind: "claude", Interactive: true, Permission: "auto", Model: "opus", Workdir: "/w", SessionUUID: "UU-1"},
			wantCommand: "cd '/w' && claude --model opus --permission-mode auto --session-id UU-1 'T'",
			// 注意：一次性形态**不带** --session-id —— 它只在交互式那条路上注入。
			wantFromFn:  "cd '/w' && claude -p --model opus --permission-mode auto --output-format text < '/p.txt'",
			wantInterFn: "cd '/w' && claude --model opus --permission-mode auto --session-id UU-1 \"$(cat '/p.txt')\"",
		},
		{
			name:        "codex/一次性/auto 权限也要 bypass",
			ac:          AgentConfig{CodexBin: "codex", Kind: "codex", Permission: "auto", Workdir: "/w", Model: "gpt"},
			wantCommand: "cd '/w' && codex exec --skip-git-repo-check -m gpt --dangerously-bypass-approvals-and-sandbox - <<'TTMUX_TASK_EOF'\nT\nTTMUX_TASK_EOF",
			wantFromFn:  "cd '/w' && codex exec --skip-git-repo-check -m gpt --dangerously-bypass-approvals-and-sandbox - < '/p.txt'",
			wantInterFn: "cd '/w' && codex -m gpt \"$(cat '/p.txt')\"",
		},
		{
			name: "codex/交互/给了对话 id 也不该出现在命令里",
			ac:   AgentConfig{CodexBin: "codex", Kind: "codex", Interactive: true, Model: "gpt", Workdir: "/w", SessionUUID: "UU-3"},
			// codex 没有 --session-id 这类参数，硬塞进去它会起不来。
			// 这条盯着「别顺手给它也加上」。
			wantCommand: "cd '/w' && codex -m gpt 'T'",
			wantFromFn:  "cd '/w' && codex exec --skip-git-repo-check -m gpt - < '/p.txt'",
			wantInterFn: "cd '/w' && codex -m gpt \"$(cat '/p.txt')\"",
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := c.ac.Command("T"); got != c.wantCommand {
				t.Errorf("Command()\n got=%q\nwant=%q", got, c.wantCommand)
			}
			if got := c.ac.CommandFromPromptFile("/p.txt"); got != c.wantFromFn {
				t.Errorf("CommandFromPromptFile()\n got=%q\nwant=%q", got, c.wantFromFn)
			}
			if got := c.ac.InteractiveFromPromptFile("/p.txt"); got != c.wantInterFn {
				t.Errorf("InteractiveFromPromptFile()\n got=%q\nwant=%q", got, c.wantInterFn)
			}
		})
	}
}

// bin 可被配置覆盖（用户装在别处 / 用 wrapper 包了一层）。
// 重构时最容易漏掉的就是这个覆盖，因为默认值恰好等于二进制名，测不出来。
func TestBinOverrideHonored(t *testing.T) {
	ac := AgentConfig{ClaudeBin: "/opt/cc/claude", Kind: "claude", Permission: "auto", Workdir: "/w"}
	if got := ac.Command("T"); got[:len("cd '/w' && /opt/cc/claude")] != "cd '/w' && /opt/cc/claude" {
		t.Errorf("claude bin 覆盖没生效: %q", got)
	}
	cx := AgentConfig{CodexBin: "/opt/cx/codex", Kind: "codex", Interactive: true, Workdir: "/w"}
	if got := cx.Command("T"); got != "cd '/w' && /opt/cx/codex 'T'" {
		t.Errorf("codex bin 覆盖没生效: %q", got)
	}
}

// 认不出的 kind 要退回默认那型，而不是拼出一条空命令交给 shell。
func TestUnknownKindFallsBackToDefault(t *testing.T) {
	ac := AgentConfig{Kind: "gemini", Permission: "auto", Workdir: "/w"}
	got := ac.Command("T")
	if got == "" || got == "cd '/w' && " {
		t.Fatalf("未知 kind 拼出了空命令: %q", got)
	}
}
