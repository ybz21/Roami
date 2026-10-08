package api

import "testing"

// 会话跑的是哪个 agent，只能看启动段，不能扫整条命令行：prompt 就在 argv 里。
// 真机上出过这事——一个 codex 会话的 prompt 里写了「claude 分析到了一些东西」，
// 整条 Contains("claude") 就把它标成了 Claude 会话（图标、工具条、对话视图全跟着错）。
func TestAgentKindIgnoresPromptText(t *testing.T) {
	cases := []struct {
		name   string
		argv   []string
		claude bool
		codex  bool
	}{
		{
			name:  "codex 的 prompt 里提到 claude",
			argv:  []string{"node", "/home/ai/.local/bin/codex", "分析下。claude分析到了一些东西，你也看下"},
			codex: true,
		},
		{
			name:  "rust codex 直接把 prompt 当 argv[1]",
			argv:  []string{"codex", "claude 说要先切分支"},
			codex: true,
		},
		{
			name:   "claude 的 prompt 里提到 codex",
			argv:   []string{"node", "/home/ai/.local/bin/claude", "把 codex 那版实现也读一下"},
			claude: true,
		},
		{
			name:   "npm 全局装的 claude：argv[1] 是 cli.js，得靠整条路径认",
			argv:   []string{"/usr/bin/node", "/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"},
			claude: true,
		},
		{
			name: "claude 把 codex 当 MCP server 拉起来的不算会话",
			argv: []string{"codex", "mcp-server"},
		},
		{
			name: "ttmux 自己（codex-web）不算",
			argv: []string{"/home/ai/codes/ttmux/backend/codex-web", "-web", "/home/ai/codes/ttmux/frontend/dist"},
		},
		{
			name: "光是 cwd/参数里带名字，不是在跑 agent",
			argv: []string{"bash", "-lc", "grep -r claude /home/ai/codes/codex-notes"},
		},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if got := argvIsClaude(c.argv); got != c.claude {
				t.Errorf("argvIsClaude = %v, want %v (argv=%q)", got, c.claude, c.argv)
			}
			if got := argvIsCodex(c.argv); got != c.codex {
				t.Errorf("argvIsCodex = %v, want %v (argv=%q)", got, c.codex, c.argv)
			}
		})
	}
}

func TestOpenCodeAndPiLaunchArgs(t *testing.T) {
	cases := []struct {
		argv         []string
		openCode, pi bool
	}{
		{argv: []string{"/usr/local/bin/opencode", "pi should review this"}, openCode: true},
		{argv: []string{"node", "/usr/lib/node_modules/opencode-ai/bin/opencode", "hello"}, openCode: true},
		{argv: []string{"/home/ai/.local/bin/pi", "opencode can help"}, pi: true},
		{argv: []string{"node", "/usr/lib/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"}, pi: true},
		{argv: []string{"bash", "-lc", "cd /home/ai/opencode && pi"}},
		{argv: []string{"/usr/bin/ping", "pi"}},
	}
	for _, c := range cases {
		if got := argvIsOpenCode(c.argv); got != c.openCode {
			t.Errorf("argvIsOpenCode(%q) = %v, want %v", c.argv, got, c.openCode)
		}
		if got := argvIsPi(c.argv); got != c.pi {
			t.Errorf("argvIsPi(%q) = %v, want %v", c.argv, got, c.pi)
		}
	}
}
