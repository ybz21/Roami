package im

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

func testCtx(t *testing.T) *sdk.Ctx {
	t.Helper()
	return &sdk.Ctx{Config: map[string]string{"workspace": t.TempDir(), "owner_open_id": "ou_owner"}}
}

func TestEnsureWorkspaceAndInbox(t *testing.T) {
	ctx := testCtx(t)
	if err := ensureWorkspace(ctx); err != nil {
		t.Fatal(err)
	}
	for _, f := range []string{"AGENT.md", "MEMORY.md", "tasks"} {
		if _, err := os.Stat(filepath.Join(workspaceDir(ctx), f)); err != nil {
			t.Fatalf("workspace missing %s: %v", f, err)
		}
	}
	// AGENT.md 已存在则不覆盖
	custom := filepath.Join(workspaceDir(ctx), "AGENT.md")
	if err := os.WriteFile(custom, []byte("我的自定义角色"), 0o644); err != nil {
		t.Fatal(err)
	}
	_ = ensureWorkspace(ctx)
	if b, _ := os.ReadFile(custom); string(b) != "我的自定义角色" {
		t.Fatal("AGENT.md was overwritten")
	}

	// 追加三条,游标推进与重放窗口
	for _, txt := range []string{"a", "b", "c"} {
		if _, err := appendInbox(ctx, inboxItem{Type: "user", Chat: "oc_1", Sender: "ou_owner", Text: txt}); err != nil {
			t.Fatal(err)
		}
	}
	total, err := countInboxLines(inboxPath(ctx))
	if err != nil || total != 3 {
		t.Fatalf("want 3 lines, got %d err=%v", total, err)
	}
	if c := readCursor(ctx); c != 0 {
		t.Fatalf("fresh cursor should be 0, got %d", c)
	}
	writeCursor(ctx, 2)
	if c := readCursor(ctx); c != 2 {
		t.Fatalf("cursor roundtrip failed: %d", c)
	}
}

func TestSenderAllowed(t *testing.T) {
	ctx := testCtx(t)
	if !senderAllowed(ctx, "oc_any", "ou_owner") {
		t.Fatal("owner should be allowed")
	}
	if senderAllowed(ctx, "oc_any", "ou_stranger") {
		t.Fatal("stranger should be refused")
	}
	ctx.Config["allow_users"] = "ou_friend, ou_mate"
	if !senderAllowed(ctx, "oc_any", "ou_mate") {
		t.Fatal("allow_users should be allowed")
	}
	ctx.Config["allow_chats"] = "oc_home"
	if senderAllowed(ctx, "oc_other", "ou_owner") {
		t.Fatal("chat restriction should apply when allow_chats set")
	}
	if !senderAllowed(ctx, "oc_home", "ou_owner") {
		t.Fatal("allowed chat should pass")
	}
	// 无 owner 时一律拒
	ctx2 := &sdk.Ctx{Config: map[string]string{"workspace": t.TempDir()}}
	if senderAllowed(ctx2, "oc_any", "ou_owner") {
		t.Fatal("no owner bootstrap → refuse all")
	}
}

func TestWorkerContract(t *testing.T) {
	c := workerContract("oc_1", "im-w-x", "/w/tasks/w-x/RESULT.md", true)
	for _, want := range []string{"RESULT.md", "im-bridge.send --chat oc_1", "tmux kill-session -t im-w-x"} {
		if !strings.Contains(c, want) {
			t.Fatalf("contract missing %q:\n%s", want, c)
		}
	}
	c2 := workerContract("", "im-w-y", "/r.md", false)
	if strings.Contains(c2, "im-bridge.send") || strings.Contains(c2, "kill-session") {
		t.Fatalf("one-shot contract without chat should not offer send/kill:\n%s", c2)
	}
}

func TestWorkspaceTildeExpansion(t *testing.T) {
	ctx := &sdk.Ctx{Config: map[string]string{"workspace": "~/x/y"}}
	home, _ := os.UserHomeDir()
	if got := workspaceDir(ctx); got != filepath.Join(home, "x", "y") {
		t.Fatalf("tilde not expanded: %s", got)
	}
	ctx2 := &sdk.Ctx{Config: map[string]string{}}
	if got := workspaceDir(ctx2); !strings.HasSuffix(got, filepath.Join(".roami", "plugins", "im", "workspace")) {
		t.Fatalf("default workspace wrong: %s", got)
	}
}
