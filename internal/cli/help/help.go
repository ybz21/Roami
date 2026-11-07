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
	fmt.Fprintf(w, "    %s %s   关闭会话 %s\n", g("kill"), d("<会话> [--cascade]"), d("(默认孤儿收养子会话)"))
	fmt.Fprintf(w, "    %s %s  发送具名按键或单个字母数字\n", g("keys"), d("<会话> <按键...>"))
	fmt.Fprintf(w, "    %s %s  重命名会话\n\n", g("rename"), d("<旧名> <新名>"))
	fmt.Fprintf(w, "    %s %s  暂停 / 继续会话（保留进程与终端）\n\n", g("pause | resume"), d("<会话> [--json]"))

	fmt.Fprintln(w, "    reclaim | compact <会话> [--json]  回收内存 / 整理空闲 Agent 上下文")
	fmt.Fprintln(w, "    memory-status | memory-setup-script  压缩交换区状态 / 管理员启用脚本")
	fmt.Fprintf(w, "  %s %s\n", b("子会话"), m("(subSession — 平坦 tmux 会话 + parent 关系)"))
	fmt.Fprintf(w, "    %s %s  从父会话派生子会话(继承 cwd/env)\n", g("fork"), d("[<父>] <子> [--dir <目录>] [--detach] [--json]"))
	fmt.Fprintf(w, "    %s %s  会话树(parent 投影)\n", g("ls --tree"), d("[--json]"))
	fmt.Fprintf(w, "    %s  活会话身份快照；观察失败返回错误\n", g("ls --live --json"))
	fmt.Fprintf(w, "    %s %s  严格解析；同名不自动选择\n", g("resolve <session> --strict"), d("[--json]"))
	fmt.Fprintf(w, "    %s %s  列出直接子会话\n", g("children"), d("<会话> [--json]"))
	fmt.Fprintf(w, "    %s %s  调整归属\n\n", g("parent"), d("set <子> <父> | clear <子> | get <子>"))

	fmt.Fprintln(w, "  蜂群编排 (Roami Main)")
	fmt.Fprintln(w, "    swarm new <名> --key KEY --goal <目标> [--main-conversation ID] [--dir DIR]")
	fmt.Fprintln(w, "    roami swarm help  完整蜂群命令；roami session swarm 访问同一实现")
	fmt.Fprintln(w, "    swarm ls | status/board/chat <sw-id> [--follow] [--json]")
	fmt.Fprintln(w, "    swarm plan/dependencies/control/say/post <sw-id> --file <request.json>")
	fmt.Fprintln(w, "    swarm members/work/collect <sw-id>; pause/resume/stop/archive <sw-id> --key KEY --revision N")
	fmt.Fprintln(w, "    Main 编排计划；成员结果经任务验收，看板随真实状态更新")

	fmt.Fprintf(w, "  %s\n", b("窗口 / 窗格"))
	fmt.Fprintf(w, "    %s %s  新建窗口   %s 列出窗口   %s %s 关闭窗口\n", g("nw"), d("[名称]"), g("lw"), g("kw"), d("[窗口号]"))
	fmt.Fprintf(w, "    %s %s  分割窗格   %s 关闭窗格\n\n", g("sp"), d("[-h|-v]"), g("kp"))

	fmt.Fprintf(w, "  %s\n", b("全局环境变量"))
	fmt.Fprintf(w, "    %s %s | %s %s | %s | %s\n\n",
		g("env set"), d("<K=V>"), g("env rm"), d("<KEY>"), g("env clear"), g("env push"))

	fmt.Fprintf(w, "  %s\n", b("其他"))
	fmt.Fprintf(w, "    %s 服务器信息   %s 安装补全   %s 显示帮助\n",
		g("info"), g("completion"), g("help"))
	fmt.Fprintf(w, "    %s %s  台账库：状态 / 迁移 / 备份\n\n",
		g("roami db"), d("status|migrate|backup [--json]"))

	fmt.Fprintf(w, "  %s\n\n", d("仅支持上列业务命令；不转发原生 tmux 命令"))
}
