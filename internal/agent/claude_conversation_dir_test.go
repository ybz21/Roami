package agent

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// claude 的对话文件会随 worktree 搬家：目录名转义有损，所以读记录里的 cwd，
// 且取**最后一条**——第一条是建会话时的目录，正是台账已经记着的那个。
func TestClaudeConversationDirReadsLastCwd(t *testing.T) {
	root := t.TempDir()
	orig := claudeProjectsRoot
	claudeProjectsRoot = func() string { return root }
	defer func() { claudeProjectsRoot = orig }()

	dir := filepath.Join(root, "-home-u-repo--claude-worktrees-x")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	// 中间夹一行超长（工具结果）和一行没有 cwd 的记录
	long := strings.Repeat("x", 200_000)
	body := `{"type":"summary","sessionId":"C1"}` + "\n" +
		`{"type":"user","cwd":"/home/u/repo","message":"hi"}` + "\n" +
		`{"type":"assistant","cwd":"/home/u/repo","message":"` + long + `"}` + "\n" +
		`{"type":"user","cwd":"/home/u/repo/.claude/worktrees/x","message":"go"}` + "\n" +
		`{"type":"last-prompt","leafUuid":"L"}` // 末行不带换行
	if err := os.WriteFile(filepath.Join(dir, "C1.jsonl"), []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}

	if got := Get("claude").ConversationDir("C1"); got != "/home/u/repo/.claude/worktrees/x" {
		t.Fatalf("该取最后一条记录的 cwd，得到 %q", got)
	}
	if got := Get("claude").ConversationDir("nope"); got != "" {
		t.Fatalf("找不到对话文件该返回空串，得到 %q", got)
	}
	if got := ConversationDirFor("codex", "C1"); got != "" {
		t.Fatalf("codex 不知道对话目录，该返回空串，得到 %q", got)
	}
}
