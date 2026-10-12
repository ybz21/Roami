package pty

import (
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

// 这组测试跑真 tmux：验证「什么时候允许给应用合成鼠标滚轮」。
// 背景 bug：只按 alternate_on 判断就合成 SGR 滚轮，喂给没开鼠标上报的应用时字节不会被消费，
// readline / TUI 输入行会把 ESC[< 之后的部分当普通字符吃进去，命令行被
// "65;137;33M65;137;33M…" 灌满、整屏花掉。

func requireTmux(t *testing.T) {
	t.Helper()
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("无 tmux，跳过")
	}
}

// newSession 起一个跑 cmdline 的临时 tmux 会话，测试结束自动清理。
func newSession(t *testing.T, name, cmdline string) string {
	t.Helper()
	name = name + "-" + strconv.Itoa(os.Getpid())
	_ = exec.Command("tmux", "kill-session", "-t", "="+name).Run()
	if err := exec.Command("tmux", "new-session", "-d", "-s", name, "-x", "80", "-y", "24", cmdline).Run(); err != nil {
		t.Skipf("起 tmux 会话失败(无可用 tmux server?): %v", err)
	}
	t.Cleanup(func() { _ = exec.Command("tmux", "kill-session", "-t", "="+name).Run() })
	time.Sleep(600 * time.Millisecond) // 等应用进备用屏、开鼠标模式
	return name
}

// tmuxProp 问 tmux 要某个 pane 变量的真值（断言「真的滚了」用，不看被吞掉的返回码）。
func tmuxProp(t *testing.T, name, format string) string {
	t.Helper()
	out, err := exec.Command("tmux", "display-message", "-p", "-t", "="+name+":", format).Output()
	if err != nil {
		t.Fatalf("display-message %s: %v", format, err)
	}
	return strings.TrimSpace(string(out))
}

func capture(t *testing.T, name string) string {
	t.Helper()
	out, err := exec.Command("tmux", "capture-pane", "-t", "="+name+":", "-p").Output()
	if err != nil {
		t.Fatalf("capture-pane: %v", err)
	}
	return string(out)
}

// 造一个足够长的文件供 less 翻页
func longFile(t *testing.T) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "long.txt")
	var b strings.Builder
	for i := 0; i < 400; i++ {
		b.WriteString("line-" + strconv.Itoa(i) + "\n")
	}
	if err := os.WriteFile(p, []byte(b.String()), 0o644); err != nil {
		t.Fatal(err)
	}
	return p
}

// 备用屏但没开鼠标上报：用翻页键滚动，不能把滚轮序列打进输入行。
func TestScrollAltScreenWithoutMouseUsesPageKeys(t *testing.T) {
	requireTmux(t)
	if _, err := exec.LookPath("less"); err != nil {
		t.Skip("无 less，跳过")
	}
	name := newSession(t, "ptytest-nomouse", "less "+longFile(t))

	alt, mouseOn, _, _, _ := paneState(name)
	if !alt {
		t.Skipf("less 未进备用屏(alt=%v)，环境不支持本用例", alt)
	}
	if mouseOn {
		t.Skip("该 less 默认开了鼠标上报，本用例不适用")
	}

	before := capture(t, name)
	if inCopy := tmuxScroll(name, "down", 5); inCopy {
		t.Error("备用屏不应进入 copy-mode")
	}
	time.Sleep(300 * time.Millisecond)
	after := capture(t, name)

	// 关键断言：屏幕不该出现滚轮序列的残骸（去掉 ESC[< 后剩下的 "<btn>;<col>;<row>M"）
	for _, junk := range []string{"64;", "65;", ";40;12M", "M64", "M65"} {
		if strings.Contains(after, junk) {
			t.Fatalf("合成的滚轮字节被当普通输入吃进去了，屏幕出现 %q:\n%s", junk, after)
		}
	}
	if after == before {
		t.Errorf("没开鼠标上报时翻页键应滚动应用\n--- before ---\n%s\n--- after ---\n%s", before, after)
	}
}

func TestPageTurnLimitsTouchBurst(t *testing.T) {
	var ws wheelState
	now := time.Now()
	if !ws.pageTurn("up", now) || ws.pageTurn("up", now.Add(100*time.Millisecond)) {
		t.Fatal("同向滑动应在短时间内只翻一页")
	}
	if !ws.pageTurn("down", now.Add(100*time.Millisecond)) || !ws.pageTurn("down", now.Add(350*time.Millisecond)) {
		t.Fatal("反向滑动及间隔后的滑动应立即响应")
	}
}

// 普通屏（shell 提示符）：走 tmux copy-mode 滚真实 scrollback，且不得把滚轮字节打进命令行。
// 这正是用户遇到的现场——普通 bash 会话被 "65;137;33M…" 灌满。
func TestScrollNormalScreenUsesCopyModeNotWheel(t *testing.T) {
	requireTmux(t)
	name := newSession(t, "ptytest-shell", "bash --norc --noprofile")
	// 先产生一屏以上的历史，copy-mode 才有东西可滚
	_ = exec.Command("tmux", "send-keys", "-t", "="+name+":", "for i in $(seq 1 200); do echo history-line-$i; done", "C-m").Run()
	time.Sleep(800 * time.Millisecond)

	if alt, mouseOn, _, _, _ := paneState(name); alt || mouseOn {
		t.Skipf("普通 shell 会话状态异常 alt=%v mouseOn=%v", alt, mouseOn)
	}

	inCopy := tmuxScroll(name, "up", 5)
	time.Sleep(300 * time.Millisecond)
	after := capture(t, name)

	if !inCopy {
		t.Error("普通屏向上滚应进入 copy-mode")
	}
	// 只信返回值不够：tmuxScroll 里的 tmux 命令是 `_ =` 吞掉错误的，目标写错时它
	// 照样报「进了 copy-mode」，而实际上 tmux 回的是 can't find pane，屏幕一动不动。
	// 这里问 tmux 要真相——翻页失效那次就是这么漏过去的。
	if mode := tmuxProp(t, name, "#{pane_in_mode}"); mode != "1" {
		t.Errorf("tmux 说自己没在 copy-mode(pane_in_mode=%q)：命令根本没落到 pane 上", mode)
	}
	if pos := tmuxProp(t, name, "#{scroll_position}"); pos == "" || pos == "0" {
		t.Errorf("scroll_position=%q，说明没真的往上滚", pos)
	}
	for _, junk := range []string{"64;", "65;", "33M", "M64", "M65"} {
		if strings.Contains(after, junk) {
			t.Fatalf("普通屏不该收到合成滚轮，屏幕出现 %q:\n%s", junk, after)
		}
	}
	// 退出 copy-mode，别把会话留在滚动状态
	tmuxScroll(name, "bottom", 0)
}

// 备用屏 + 开了鼠标上报：应当真的合成滚轮并让应用滚动（less --mouse 会翻页）。
func TestScrollAltScreenWithMouseScrolls(t *testing.T) {
	requireTmux(t)
	if _, err := exec.LookPath("less"); err != nil {
		t.Skip("无 less，跳过")
	}
	name := newSession(t, "ptytest-mouse", "less --mouse "+longFile(t))

	alt, mouseOn, _, _, _ := paneState(name)
	if !alt || !mouseOn {
		t.Skipf("less --mouse 未开鼠标上报(alt=%v mouseOn=%v)，环境不支持本用例", alt, mouseOn)
	}

	before := capture(t, name)
	tmuxScroll(name, "down", 5)
	time.Sleep(400 * time.Millisecond)
	after := capture(t, name)

	if after == before {
		t.Errorf("开了鼠标上报时滚轮应生效，但屏幕没变:\n%s", after)
	}
	if strings.Contains(after, "64;") || strings.Contains(after, "65;") {
		t.Errorf("滚轮序列被当普通文本显示了:\n%s", after)
	}
}
