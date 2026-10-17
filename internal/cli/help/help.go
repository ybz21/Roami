// Package help renders the top-level usage screen (mirrors lib/help.sh).
package help

import (
	"fmt"
	"io"

	"github.com/ybz21/Roami/internal/terminalui"
)

// Show prints the help screen.
func Show(version string, w io.Writer) {
	p := ui.P()
	b := func(s string) string { return ui.Bold(s) }
	g := func(s string) string { return p.Green + s + p.Reset }
	d := func(s string) string { return p.Dim + s + p.Reset }
	c := func(s string) string { return p.Cyan + s + p.Reset }
	m := func(s string) string { return p.Magenta + s + p.Reset }

	fmt.Fprintf(w, "\n  %s %s\n\n", b("roami session"), d("v"+version+" — AI-native tmux wrapper"))
	fmt.Fprintf(w, "  %s:  roami session %s [参数...]\n\n", b("用法"), c("<命令>"))

	fmt.Fprintf(w, "  %s\n", b("会话管理"))
	fmt.Fprintf(w, "    %s %s  列出所有会话\n", g("ls"), d("[--json]"))
	fmt.Fprintf(w, "    %s %s   新建会话\n", g("new"), d("[名称]"))
	fmt.Fprintf(w, "    %s %s   附加会话 %s\n", g("a"), d("[名称]"), d("(无参数交互选择)"))
	fmt.Fprintf(w, "    %s %s   分离会话\n", g("d"), d("[名称]"))
	fmt.Fprintf(w, "    %s %s   关闭会话 %s\n", g("kill"), d("[名称] [--cascade]"), d("(默认孤儿收养子会话)"))
	fmt.Fprintf(w, "    %s            关闭所有会话\n", g("killall"))
	fmt.Fprintf(w, "    %s %s  重命名会话\n\n", g("rename"), d("<旧名> <新名>"))

	fmt.Fprintf(w, "  %s %s\n", b("子会话"), m("(subSession — 平坦 tmux 会话 + parent 关系)"))
	fmt.Fprintf(w, "    %s %s  从父会话派生子会话(继承 cwd/env)\n", g("fork"), d("[<父>] <子> [--dir <目录>] [--detach] [--json]"))
	fmt.Fprintf(w, "    %s %s  会话树(parent 投影)\n", g("ls --tree"), d("[--json]"))
	fmt.Fprintf(w, "    %s %s  列出直接子会话\n", g("children"), d("<会话> [--json]"))
	fmt.Fprintf(w, "    %s %s  调整归属\n\n", g("parent"), d("set <子> <父> | clear <子> | get <子>"))

	fmt.Fprintf(w, "  %s %s\n", b("蜂群编排"), m("(swarm — 有目标的任务组)"))
	fmt.Fprintf(w, "    %s %s  新建蜂群\n", g("swarm new"), d("<名> [--goal \"...\"] [--no-master]"))
	fmt.Fprintf(w, "    %s %s  加成员\n", g("swarm add"), d("<群> <成员> --type task|agent [--kind claude|codex] ..."))
	fmt.Fprintf(w, "    %s %s  列出 / 状态\n", g("swarm ls|status"), d("[<群>] [--json]"))
	fmt.Fprintf(w, "    %s %s  解锁挂起 / 标记完成\n", g("swarm activate|done"), d("<群> [成员]"))
	fmt.Fprintf(w, "    %s %s  cc 接管 / 归档 / 删除\n", g("swarm adopt|archive|rm"), d("<群>"))
	fmt.Fprintf(w, "    %s %s  广场: 发言 / 读流 / 监听 / 跟随\n", g("swarm say|feed|listen|watch"), d("<群> ..."))
	fmt.Fprintf(w, "    %s %s  看板: 全貌 / 卡片\n", g("swarm board|task"), d("<群> ..."))
	fmt.Fprintf(w, "    %s %s  只读查每群 swarm.db\n\n", g("swarm sql"), d("<群> [--json] \"SELECT ...\""))

	fmt.Fprintf(w, "  %s\n", b("窗口 / 窗格"))
	fmt.Fprintf(w, "    %s %s  新建窗口   %s 列出窗口   %s %s 关闭窗口\n", g("nw"), d("[名称]"), g("lw"), g("kw"), d("[窗口号]"))
	fmt.Fprintf(w, "    %s %s  分割窗格   %s 关闭窗格\n\n", g("sp"), d("[-h|-v]"), g("kp"))

	fmt.Fprintf(w, "  %s\n", b("全局环境变量"))
	fmt.Fprintf(w, "    %s %s | %s %s | %s | %s\n\n",
		g("env set"), d("<K=V>"), g("env rm"), d("<KEY>"), g("env clear"), g("env push"))

	fmt.Fprintf(w, "  %s\n", b("其他"))
	fmt.Fprintf(w, "    %s 服务器信息   %s 重载 tmux.conf   %s 安装补全   %s 显示帮助\n",
		g("info"), g("source"), g("completion"), g("help"))
	fmt.Fprintf(w, "    %s %s  台账库：状态 / 迁移 / 备份\n\n",
		g("roami db"), d("status|migrate|backup [--json]"))

	fmt.Fprintf(w, "  %s\n\n", d("未识别的命令会直接转发给 tmux"))
}
