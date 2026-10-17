// Package interactive implements the menu-driven mode (mirrors lib/interactive.sh).
// Real actions are dispatched through the native command router (run), so the
// interactive paths behave identically to the equivalent CLI invocations.
package interactive

import (
	"fmt"
	"os"
	"strconv"
	"strings"

	swarmcore "github.com/ybz21/Roami/internal/swarm"
	"github.com/ybz21/Roami/internal/terminalui"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// Runner dispatches a CLI argument vector (typically app.Run).
type Runner func(args []string) error

type menu struct {
	rt  runtime.Runtime
	run Runner
	st  *swarmcore.Store
}

// Run starts the interactive loop.
func Run(rt runtime.Runtime, version string, run Runner) error {
	m := &menu{rt: rt, run: run, st: swarmcore.NewStore(swarmcore.Options{
		HomeDir: rt.HomeDir, DataDir: rt.DataDir, TmuxBin: rt.TmuxBin, Now: rt.Now,
	})}
	for {
		m.header(version)
		m.mainMenu()
		choice, _ := ui.ReadLine("  选择操作: ")
		fmt.Println()
		switch choice {
		case "1":
			_ = m.run([]string{"ls"})
			m.pause()
		case "2":
			name, _ := ui.ReadLine("  会话名称 (空=自动): ")
			if name == "" {
				_ = m.run([]string{"new"})
			} else {
				_ = m.run([]string{"new", name})
			}
		case "3":
			_ = m.run([]string{"a"})
		case "4":
			_ = m.run([]string{"kill"})
			m.pause()
		case "5":
			m.swarmMenu()
		case "6":
			_ = m.run([]string{"swarm", "ls"})
			_ = m.run([]string{"ls"})
			m.pause()
		case "s":
			if t, ok := m.pickSession("发送命令到"); ok {
				if cmd, _ := ui.ReadLine("  命令: "); cmd != "" {
					_ = m.run([]string{"send", t, cmd})
				}
			}
			m.pause()
		case "h":
			_ = m.run([]string{"help"})
			m.pause()
		case "q", "0", "":
			fmt.Printf("  %sbye%s\n\n", ui.P().Dim, ui.P().Reset)
			return nil
		default:
			ui.Warn(os.Stdout, "无效选择")
			m.pause()
		}
	}
}

func (m *menu) header(version string) {
	clear()
	p := ui.P()
	fmt.Printf("\n  %s %s  %s\n", ui.Bold("ttmux"), ui.Dim("v"+version), ui.Dim("— 交互模式 (q 退出)"))
	fmt.Printf("  %s%s%s\n", p.Dim, strings.Repeat("─", 44), p.Reset)
	swarms, _ := m.st.ListSwarms()
	fmt.Printf("  %s会话: %s%s%d%s%s  蜂群: %s%s%d%s\n\n",
		p.Dim, p.Reset, p.Bold, len(m.rt.Sessions()), p.Reset, p.Dim, p.Reset, p.Bold, len(swarms), p.Reset)
}

func (m *menu) mainMenu() {
	p := ui.P()
	c := func(s string) string { return p.Cyan + s + p.Reset }
	fmt.Printf("  %s\n", ui.Bold("会话"))
	fmt.Printf("    %s) 列出会话          %s) 新建会话\n", c("1"), c("2"))
	fmt.Printf("    %s) 附加会话          %s) 关闭会话\n\n", c("3"), c("4"))
	fmt.Printf("  %s %s\n", ui.Bold("蜂群编排"), p.Magenta+"(swarm)"+p.Reset)
	fmt.Printf("    %s) 蜂群编排 ▸        %s) 状态总览\n\n", c("5"), c("6"))
	fmt.Printf("  %s\n", ui.Bold("其他"))
	fmt.Printf("    %s) 发送命令          %s) 帮助\n\n", c("s"), c("h"))
}

// ── helpers ──

func clear() { fmt.Print("\033[H\033[2J") }

func (m *menu) pause() {
	_, _ = ui.ReadLine("\n  按回车继续...")
}

// runningLabel 吃的可能是展示名（蜂群成员的 `<群>-<成员>`），先解析成会话名。
func (m *menu) runningLabel(sess string) string {
	if m.rt.HasSession(m.rt.ResolveAlive(sess)) {
		return " " + ui.P().Yellow + "运行中" + ui.P().Reset
	}
	return " " + ui.Dim("已结束")
}

func (m *menu) pickSession(prompt string) (string, bool) {
	var names []string
	excl := swarmcore.SessionNames(m.st.Options())
	for _, s := range m.rt.Sessions() {
		if !excl[s] {
			names = append(names, s)
		}
	}
	return m.pickFrom(prompt, names, nil)
}

// pickFrom prints a numbered list and returns the chosen item.
func (m *menu) pickFrom(prompt string, items []string, label func(string) string) (string, bool) {
	if len(items) == 0 {
		ui.Info(os.Stdout, "没有可选项")
		return "", false
	}
	if len(items) == 1 {
		return items[0], true
	}
	p := ui.P()
	fmt.Printf("\n  %s:\n", ui.Bold(prompt))
	for i, it := range items {
		suffix := ""
		if label != nil {
			suffix = label(it)
		}
		fmt.Printf("    %s%d%s) %s%s\n", p.Cyan, i+1, p.Reset, it, suffix)
	}
	choice, _ := ui.ReadLine("\n  编号: ")
	if n, err := strconv.Atoi(choice); err == nil && n >= 1 && n <= len(items) {
		return items[n-1], true
	}
	return "", false
}
