package agent

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// 每一型都得答得上这几个问题。新增一型时这条会自动把它带上——
// 忘了实现哪一项，红的是这里，而不是半年后某个用户的会话恢复不出来。
func TestEveryAgentAnswersTheContract(t *testing.T) {
	kinds := Kinds()
	if len(kinds) < 2 {
		t.Fatalf("至少该注册 claude 和 codex，现在只有 %v", kinds)
	}
	for _, k := range kinds {
		a := Get(k)
		if a == nil {
			t.Fatalf("Kinds() 报了 %q 但 Get 拿不到", k)
		}
		if a.Kind() != k {
			t.Errorf("%s: Kind() 与注册名不一致（%q）", k, a.Kind())
		}
		if strings.TrimSpace(a.DisplayName()) == "" {
			t.Errorf("%s: DisplayName 为空", k)
		}
		if strings.TrimSpace(a.Bin()) == "" {
			t.Errorf("%s: Bin 为空", k)
		}
		// 恢复命令必须含对话 id —— 少了它就是「恢复到最近一段」，
		// 那会接错对话，比不恢复更糟。
		cmd := a.ResumeCommand("11111111-2222-3333-4444-555555555555")
		if cmd == "" {
			t.Logf("%s: 这一型接不回对话（可以，但列表里 resumable 会是 false）", k)
			continue
		}
		if !strings.Contains(cmd, "11111111-2222-3333-4444-555555555555") {
			t.Errorf("%s: 恢复命令没带上对话 id: %q", k, cmd)
		}
		if !strings.HasPrefix(cmd, a.Bin()) {
			t.Errorf("%s: 恢复命令没以 Bin() 开头: %q", k, cmd)
		}
	}
}

// 空 id 一律不给命令。调用方拿到空串就只开壳；
// 给一条不带 id 的命令等于「接回最近一段」——那是别人的对话。
func TestResumeRefusesEmptyID(t *testing.T) {
	for _, k := range Kinds() {
		if got := Get(k).ResumeCommand(""); got != "" {
			t.Errorf("%s: 空 id 却给了命令 %q", k, got)
		}
		if got := Get(k).ResumeCommand("   "); got != "" {
			t.Errorf("%s: 空白 id 却给了命令 %q", k, got)
		}
	}
}

// 认不出的类型不猜。台账里可能存着旧版本写的、或手工改进去的 kind。
func TestUnknownKindIsNil(t *testing.T) {
	if Get("gemini") != nil {
		t.Error("没注册的类型不该返回实现")
	}
	if got := ResumeCommandFor("gemini", "abc"); got != "" {
		t.Errorf("认不出类型时该返回空串，得到 %q", got)
	}
	if got := ResumeCommandFor("claude", ""); got != "" {
		t.Errorf("没有对话 id 时该返回空串，得到 %q", got)
	}
}

// 大小写/空格不该让它认不出来 —— kind 来自数据库和命令行参数。
func TestGetNormalizes(t *testing.T) {
	if Get(" Claude ") == nil || Get("CODEX") == nil {
		t.Error("Get 应当忽略大小写与首尾空格")
	}
}

// claude 能指定对话 id，codex 不能。这个差别决定了 spawn 那边走哪条路，
// 写成断言免得日后有人「顺手统一一下」。
func TestPinCapabilityDiffers(t *testing.T) {
	if !Get("claude").PinsConversationID() {
		t.Error("claude 有 --session-id，应当能指定")
	}
	if Get("codex").PinsConversationID() {
		t.Error("codex 指定不了对话 id，硬塞参数会让它起不来")
	}
}

// codex 的对话 id 只能事后从 rollout 文件名认。这条盯着那个正则：
// 文件名格式变了要立刻知道，而不是等到某次恢复悄悄只开了个壳。
func TestCodexDetectsFromRolloutFilename(t *testing.T) {
	home := t.TempDir()
	t.Setenv("CODEX_HOME", home)
	dir := filepath.Join(home, "sessions", "2026", "08", "08")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	base := time.Now().Add(-time.Hour)
	want := "019fdf01-538d-7a51-8d1d-bc278e2fcc0d"
	files := []string{
		"rollout-2026-08-08T09-33-53-019fdf00-0000-0000-0000-000000000000.jsonl", // 旧的
		"rollout-2026-08-08T10-34-58-" + want + ".jsonl",                         // 最近的
		"not-a-rollout.jsonl", // 不该被认
	}
	for i, f := range files {
		p := filepath.Join(dir, f)
		if err := os.WriteFile(p, []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
		// 拉开 mtime，确保「最近」这个判据是被真的测到的
		_ = os.Chtimes(p, base.Add(time.Duration(i)*time.Minute), base.Add(time.Duration(i)*time.Minute))
	}
	if got := Get("codex").DetectConversationID("/whatever"); got != want {
		t.Errorf("认出的是 %q，期望 %q", got, want)
	}
}

func TestCodexDetectReturnsEmptyWhenNothing(t *testing.T) {
	t.Setenv("CODEX_HOME", t.TempDir())
	if got := Get("codex").DetectConversationID("/whatever"); got != "" {
		t.Errorf("没有会话文件时该返回空串，得到 %q", got)
	}
}
