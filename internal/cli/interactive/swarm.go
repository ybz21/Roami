package interactive

import (
	"fmt"
	"os"
	"strings"

	"github.com/ybz21/Roami/internal/terminalui"
)

func (m *menu) swarmNames() []string {
	rows, _ := m.st.ListSwarms()
	var out []string
	for _, r := range rows {
		out = append(out, r.Name)
	}
	return out
}

func (m *menu) pickSwarm(prompt string) (string, bool) {
	return m.pickFrom(prompt, m.swarmNames(), func(s string) string {
		return "  " + ui.Dim("["+m.st.MetaGet(s, "status")+"]")
	})
}

func (m *menu) swarmMenu() {
	p := ui.P()
	c := func(s string) string { return p.Cyan + s + p.Reset }
	for {
		clear()
		fmt.Printf("\n  %s %s\n", ui.Bold("任务编排"), p.Magenta+"(蜂群 / swarm)"+p.Reset)
		fmt.Printf("  %s%s%s\n", p.Dim, strings.Repeat("─", 44), p.Reset)
		_ = m.run([]string{"swarm", "ls"})
		fmt.Printf("    %s) 新建蜂群          %s) 进入蜂群 ▸\n", c("n"), c("e"))
		fmt.Printf("    %s) cc 接管蜂群       %s) 归档/删除蜂群\n", c("d"), c("x"))
		fmt.Printf("    %s) 返回主菜单\n\n", c("b"))
		act, _ := ui.ReadLine("  选择: ")
		fmt.Println()
		switch act {
		case "n":
			m.swarmNew()
			m.pause()
		case "e":
			if s, ok := m.pickSwarm("进入蜂群"); ok {
				m.swarmDetail(s)
			}
		case "d":
			if s, ok := m.pickSwarm("cc 接管"); ok {
				_ = m.run([]string{"swarm", "adopt", s})
				m.pause()
			}
		case "x":
			if s, ok := m.pickSwarm("归档/删除"); ok {
				fmt.Printf("  %s1%s) 归档(留元数据)  %s2%s) 彻底删除  %s0%s) 取消\n", p.Cyan, p.Reset, p.Cyan, p.Reset, p.Cyan, p.Reset)
				xa, _ := ui.ReadLine("  选择: ")
				switch xa {
				case "1":
					_ = m.run([]string{"swarm", "archive", s})
				case "2":
					_ = m.run([]string{"swarm", "rm", s})
				}
				m.pause()
			}
		case "b", "q", "":
			return
		default:
			ui.Warn(os.Stdout, "无效选择")
			m.pause()
		}
	}
}

func (m *menu) swarmNew() {
	name, _ := ui.ReadLine("  蜂群名称: ")
	if name == "" {
		return
	}
	goal, _ := ui.ReadLine("  目标 (可空): ")
	args := []string{"swarm", "new", name}
	if goal != "" {
		args = append(args, "--goal", goal)
	}
	_ = m.run(args)
	if yn, _ := ui.ReadLine("  现在进入该蜂群加成员? [Y/n]: "); yn != "n" && yn != "N" {
		m.swarmDetail(name)
	}
}

func (m *menu) swarmDetail(swarm string) {
	p := ui.P()
	c := func(s string) string { return p.Cyan + s + p.Reset }
	for {
		clear()
		_ = m.run([]string{"swarm", "status", swarm})
		fmt.Printf("\n  %s\n", ui.Bold("蜂群 "+swarm+" ─ 成员管理"))
		fmt.Printf("    %s) 加成员            %s) 追加指令\n", c("a"), c("m"))
		fmt.Printf("    %s) 广场 ▸            %s) 看板 ▸\n", c("p"), c("t"))
		fmt.Printf("    %s) 标记成员完成      %s) 解锁挂起成员\n", c("f"), c("u"))
		fmt.Printf("    %s) 等待并收集        %s) cc 接管\n", c("c"), c("d"))
		fmt.Printf("    %s) 清理整群          %s) 返回上层\n\n", c("k"), c("b"))
		act, _ := ui.ReadLine("  选择: ")
		fmt.Println()
		switch act {
		case "a":
			m.swarmAddMember(swarm)
			m.pause()
		case "m":
			m.swarmSend(swarm)
			m.pause()
		case "p":
			m.swarmPlaza(swarm)
		case "t":
			m.swarmBoard(swarm)
		case "f":
			m.swarmMarkDone(swarm)
			m.pause()
		case "u":
			_ = m.run([]string{"swarm", "activate", swarm})
			m.pause()
		case "c":
			_ = m.run([]string{"wait", swarm})
			_ = m.run([]string{"swarm", "collect", swarm})
			m.pause()
		case "d":
			_ = m.run([]string{"swarm", "adopt", swarm})
			m.pause()
		case "k":
			if ui.Confirm("清理整群 " + ui.Bold(swarm) + " (杀全部成员会话)?") {
				_ = m.run([]string{"swarm", "archive", swarm})
			}
			m.pause()
			return
		case "b", "q", "":
			return
		default:
			ui.Warn(os.Stdout, "无效选择")
			m.pause()
		}
	}
}

func (m *menu) swarmAddMember(swarm string) {
	name, _ := ui.ReadLine("  成员名称: ")
	if name == "" {
		return
	}
	p := ui.P()
	fmt.Printf("  %s  %s1%s) shell 命令   %s2%s) Claude Agent\n", ui.Bold("类型:"), p.Cyan, p.Reset, p.Cyan, p.Reset)
	mt, _ := ui.ReadLine("  选择 [2]: ")
	if mt == "1" {
		cmd, _ := ui.ReadLine("  命令: ")
		if cmd == "" {
			ui.Warn(os.Stdout, "命令为空，取消")
			return
		}
		dep, _ := ui.ReadLine("  依赖成员 (逗号分隔, 可空): ")
		args := []string{"swarm", "add", swarm, name, "--type", "task"}
		if dep != "" {
			args = append(args, "--depends-on", dep)
		}
		_ = m.run(append(args, cmd))
		return
	}
	task, _ := ui.ReadLine("  任务描述: ")
	if task == "" {
		ui.Warn(os.Stdout, "任务为空，取消")
		return
	}
	wd, _ := os.Getwd()
	dir, _ := ui.ReadLine("  工作目录 [" + wd + "]: ")
	if dir == "" {
		dir = wd
	}
	perm, _ := ui.ReadLine("  权限 (auto/plan/default) [auto]: ")
	if perm == "" {
		perm = "auto"
	}
	dep, _ := ui.ReadLine("  依赖成员 (逗号分隔, 可空): ")
	args := []string{"swarm", "add", swarm, name, "--type", "agent", "--dir", dir, "--perm", perm}
	if dep != "" {
		args = append(args, "--depends-on", dep)
	}
	_ = m.run(append(args, task))
}

func (m *menu) memberNames(swarm string) []string {
	sessions, _ := m.rt.GroupSessions(swarm)
	var out []string
	for _, s := range sessions {
		// 台账存会话名(= id)，成员名从展示名 `<群>-<成员>` 反推（TaskLabel 会话死了也读得到）
		out = append(out, strings.TrimPrefix(m.rt.TaskLabel(m.rt.ResolveAlive(s)), swarm+"-"))
	}
	return out
}

func (m *menu) swarmSend(swarm string) {
	members := m.memberNames(swarm)
	if len(members) == 0 {
		ui.Info(os.Stdout, "该蜂群还没有成员")
		return
	}
	if sel, ok := m.pickFrom("成员", members, func(mem string) string {
		return m.runningLabel(swarm + "-" + mem)
	}); ok {
		if msg, _ := ui.ReadLine("  追加指令: "); msg != "" {
			_ = m.run([]string{"send", swarm + "-" + sel, msg})
		}
	}
}

func (m *menu) swarmMarkDone(swarm string) {
	members := m.memberNames(swarm)
	if len(members) == 0 {
		ui.Info(os.Stdout, "该蜂群还没有成员")
		return
	}
	if sel, ok := m.pickFrom("成员", members, nil); ok {
		_ = m.run([]string{"swarm", "done", swarm, sel})
	}
}

func (m *menu) swarmPlaza(swarm string) {
	for {
		clear()
		_ = m.run([]string{"swarm", "feed", swarm})
		p := ui.P()
		fmt.Printf("  %s    %ss%s) 发言   %sr%s) 刷新   %sb%s) 返回\n",
			ui.Bold("广场 "+swarm), p.Cyan, p.Reset, p.Cyan, p.Reset, p.Cyan, p.Reset)
		a, _ := ui.ReadLine("  选择: ")
		switch a {
		case "s":
			if msg, _ := ui.ReadLine("  消息: "); msg != "" {
				k, _ := ui.ReadLine("  类型(回车=note, 可: ask/block/decide/done/broadcast): ")
				if k == "" {
					k = "note"
				}
				_ = m.run([]string{"swarm", "say", swarm, "--kind", k, msg})
				m.pause()
			}
		case "b", "q", "":
			return
		}
	}
}

func (m *menu) swarmBoard(swarm string) {
	for {
		clear()
		_ = m.run([]string{"swarm", "board", swarm})
		p := ui.P()
		fmt.Printf("  %s  %sn%s) 建卡  %sg%s) 派活  %sv%s) 移动  %sr%s) 刷新  %sb%s) 返回\n",
			ui.Bold("看板 "+swarm), p.Cyan, p.Reset, p.Cyan, p.Reset, p.Cyan, p.Reset, p.Cyan, p.Reset, p.Cyan, p.Reset)
		a, _ := ui.ReadLine("  选择: ")
		switch a {
		case "n":
			if title, _ := ui.ReadLine("  卡片标题: "); title != "" {
				_ = m.run([]string{"swarm", "task", "add", swarm, title})
				m.pause()
			}
		case "g":
			cid, _ := ui.ReadLine("  卡id: ")
			who, _ := ui.ReadLine("  派给成员: ")
			if cid != "" && who != "" {
				_ = m.run([]string{"swarm", "task", "assign", swarm, cid, who})
				m.pause()
			}
		case "v":
			cid, _ := ui.ReadLine("  卡id: ")
			col, _ := ui.ReadLine("  移到列(backlog/assigned/doing/review/done/blocked): ")
			if cid != "" && col != "" {
				_ = m.run([]string{"swarm", "task", "move", swarm, cid, col})
				m.pause()
			}
		case "b", "q", "":
			return
		}
	}
}
