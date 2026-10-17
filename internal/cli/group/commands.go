package group

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// List renders the human-readable task-group table (mirrors _group_list),
// hiding swarm groups via excludeGroups.
func List(rt runtime.Runtime, excludeGroups map[string]bool, w io.Writer) error {
	matches, _ := filepath.Glob(filepath.Join(rt.GroupsDir, "*.group"))
	p := ui.P()
	var names []string
	for _, f := range matches {
		name := strings.TrimSuffix(filepath.Base(f), ".group")
		if excludeGroups[name] {
			continue
		}
		names = append(names, name)
	}
	if len(names) == 0 {
		ui.Info(w, "没有任务组")
		return nil
	}
	fmt.Fprintln(w)
	for _, g := range names {
		sessions, _ := rt.GroupSessions(g)
		total, alive := len(sessions), 0
		for _, s := range sessions {
			if rt.HasSession(rt.ResolveAlive(s)) {
				alive++
			}
		}
		var status string
		switch {
		case alive == 0 && total > 0:
			status = p.Green + "全部完成" + p.Reset
		case alive == total:
			status = p.Yellow + "运行中" + p.Reset
		default:
			status = fmt.Sprintf("%s%d/%d 运行中%s", p.Cyan, alive, total, p.Reset)
		}
		fmt.Fprintf(w, "   %s %s  %s%d 个任务%s  %s\n", ui.IconGroup, ui.Bold(g), p.Dim, total, p.Reset, status)
	}
	fmt.Fprintln(w)
	return nil
}

// Status renders the per-task status table (mirrors _status).
func Status(rt runtime.Runtime, group string, w io.Writer) error {
	if !rt.GroupExists(group) {
		ui.Err(w, "任务组 %s 不存在", ui.Bold(group))
		return fmt.Errorf("group not found")
	}
	p := ui.P()
	fmt.Fprintln(w)
	fmt.Fprintf(w, "  %s %s 状态\n", ui.IconGroup, ui.Bold(group))
	fmt.Fprintf(w, "  %s%s%s\n\n", p.Dim, strings.Repeat("─", 50), p.Reset)
	sessions, _ := rt.GroupSessions(group)
	running, done, failed := 0, 0, 0
	for _, sess := range sessions {
		sess = rt.ResolveAlive(sess) // 台账存会话 id；迁移前的老台账存名字，兜一下
		typ := rt.TaskType(sess)
		desc := firstLine(rt.TaskDesc(sess), 50)
		name := ui.Bold(rt.TaskLabel(sess)) // 展示语义名，不是 id
		tag := p.Dim + "[cmd]" + p.Reset
		if typ == "agent" {
			tag = p.Magenta + "[agent]" + p.Reset
		}
		if rt.HasSession(sess) {
			proc := strings.TrimSpace(out(rt.TmuxOutput("display-message", "-t", "="+sess+":", "-p", "#{pane_current_command}")))
			dead := strings.TrimSpace(out(rt.TmuxOutput("display-message", "-t", "="+sess+":", "-p", "#{pane_dead}")))
			if dead == "1" {
				code := strings.TrimSpace(out(rt.TmuxOutput("display-message", "-t", "="+sess+":", "-p", "#{pane_dead_status}")))
				if code == "0" {
					fmt.Fprintf(w, "  %s%s%s %s %s %s完成%s (exit 0)\n", p.Green, ui.IconOK, p.Reset, name, tag, p.Green, p.Reset)
					done++
				} else {
					fmt.Fprintf(w, "  %s%s%s %s %s %s失败%s (exit %s)\n", p.Red, ui.IconErr, p.Reset, name, tag, p.Red, p.Reset, code)
					failed++
				}
			} else {
				fmt.Fprintf(w, "  %s%s%s %s %s %s运行中%s  %s[%s]%s\n", p.Yellow, ui.IconRun, p.Reset, name, tag, p.Yellow, p.Reset, p.Dim, proc, p.Reset)
				running++
			}
		} else {
			if _, err := readLog(rt, sess); err == nil {
				fmt.Fprintf(w, "  %s%s%s %s %s %s已结束 (日志可用)%s\n", p.Green, ui.IconDone, p.Reset, name, tag, p.Dim, p.Reset)
			} else {
				fmt.Fprintf(w, "  %s%s%s %s %s %s已结束%s\n", p.Dim, ui.IconDone, p.Reset, name, tag, p.Dim, p.Reset)
			}
			done++
		}
		if desc != "" {
			fmt.Fprintf(w, "     %s↳ %s%s\n", p.Dim, desc, p.Reset)
		}
	}
	fmt.Fprintln(w)
	fmt.Fprintf(w, "  %s共 %d 个任务:  %s完成 %d%s  %s运行 %d%s  %s失败 %d%s\n\n",
		p.Dim, len(sessions), p.Green, done, p.Reset, p.Yellow, running, p.Reset, p.Red, failed, p.Reset)
	return nil
}

// Kill tears down a task group: agents get a graceful /exit first, then sessions
// are killed and metadata cleaned (mirrors _kill_group).
func Kill(rt runtime.Runtime, group string, w io.Writer) error {
	if !rt.GroupExists(group) {
		ui.Err(w, "任务组不存在: %s", group)
		return fmt.Errorf("group not found")
	}
	sessions, _ := rt.GroupSessions(group)
	for _, sess := range sessions {
		sess = rt.ResolveAlive(sess)
		if rt.HasSession(sess) {
			if rt.TaskType(sess) == "agent" {
				_ = rt.Tmux("send-keys", "-t", "="+sess+":", "/exit", "C-m")
				time.Sleep(500 * time.Millisecond)
			}
			if rt.HasSession(sess) {
				_ = rt.Tmux("kill-session", "-t", "="+sess)
			}
		}
		rt.CleanTaskMeta(sess)
	}
	_ = removeGroupFile(rt, group)
	ui.Ok(w, "任务组 %s 已清理", ui.Bold(group))
	return nil
}

// CollectText prints each task's recent output (mirrors the text path of _collect).
func CollectText(rt runtime.Runtime, group string, w io.Writer) error {
	if !rt.GroupExists(group) {
		ui.Err(w, "任务组不存在: %s", group)
		return fmt.Errorf("group not found")
	}
	p := ui.P()
	sessions, _ := rt.GroupSessions(group)
	for _, sess := range sessions {
		sess = rt.ResolveAlive(sess)
		desc := rt.TaskDesc(sess)
		fmt.Fprintln(w)
		fmt.Fprintf(w, "  %s━━━ %s ━━━%s\n", p.Bold, rt.TaskLabel(sess), p.Reset)
		if desc != "" {
			fmt.Fprintf(w, "  %s任务: %s%s\n", p.Dim, desc, p.Reset)
		}
		fmt.Fprintf(w, "  %s%s%s\n", p.Dim, strings.Repeat("─", 50), p.Reset)
		if b, err := os.ReadFile(rt.LogFile(sess)); err == nil && len(b) > 0 {
			fmt.Fprintln(w, tailString(string(b), 50))
		} else if cap, err := rt.ReadCapture(sess, "50"); err == nil {
			fmt.Fprint(w, cap)
			if !strings.HasSuffix(cap, "\n") {
				fmt.Fprintln(w)
			}
		} else {
			fmt.Fprintln(w, "  (无输出)")
		}
	}
	fmt.Fprintln(w)
	return nil
}

func firstLine(s string, max int) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		s = s[:i]
	}
	if len(s) > max {
		s = s[:max]
	}
	return s
}

func out(s string, _ error) string { return s }

func readLog(rt runtime.Runtime, sess string) (os.FileInfo, error) {
	return os.Stat(rt.LogFile(sess))
}

func removeGroupFile(rt runtime.Runtime, group string) error {
	return os.Remove(rt.GroupFile(group))
}
