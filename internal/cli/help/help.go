package help

import "io"

func Show(_ string, w io.Writer)    { _ = sessionPage().Render(w) }
func ShowAll(_ string, w io.Writer) { _ = sessionAllPage().Render(w) }

func Command(command string, w io.Writer) bool {
	page, ok := sessionCommandPage(command)
	if ok {
		_ = page.Render(w)
	}
	return ok
}

func sessionPage() Page {
	return Page{
		Command: "roami session", Summary: "管理终端会话",
		Usage: []string{
			"roami session <命令> [参数]",
			"roami session help --all",
		},
		Sections: []Section{
			{"常用命令", []Entry{
				{"ls", "列出所有会话（--tree 看层级）"},
				{"new [NAME]", "新建并进入会话（-d 后台创建）"},
				{"attach [SESSION]", "进入会话（简写 a；dev:2 可直接进第 2 个窗口）"},
				{"rename SESSION NAME", "修改会话展示名"},
				{"kill SESSION", "关闭会话"},
			}},
			{"读写与派生", []Entry{
				{"capture SESSION", "读取终端屏幕输出"},
				{"send SESSION TEXT", "向会话发送命令或消息"},
				{"fork [PARENT] NAME", "从父会话派生子会话"},
			}},
		},
		Examples: []Entry{
			{"roami session new dev", "新建并进入会话 dev"},
			{"roami session ls", "查看所有会话"},
			{"roami session a dev", "重新进入会话 dev"},
		},
		Notes: []string{
			"进入会话后无需退出敲命令：按 F2（或 Ctrl+b 空格）打开中文菜单，方向键即可分屏、切窗口、放后台。",
			"查看全部命令（窗口/分屏脚本接口、环境变量、进程与内存管理、兼容短名）：roami session help --all",
		},
		More: "roami session <命令> -h",
	}
}

func sessionAllPage() Page {
	p := sessionPage()
	p.Command = "roami session (全部命令)"
	p.Sections = append(p.Sections,
		Section{"窗口与分屏（外部脚本/API）", []Entry{
			{"window <new|ls|select|kill>", "管理会话内窗口（标签页）"},
			{"pane <ls|split|kill>", "管理窗口内分屏（--right / --down）"},
			{"detach [SESSION]", "脱离当前会话（简写 d）"},
			{"keys SESSION KEY...", "向会话发送具名按键"},
		}},
		Section{"环境与运维", []Entry{
			{"env", "管理全局环境变量（ls / set / rm / push）"},
			{"pause / resume", "暂停 / 恢复会话进程"},
			{"processes / process-stop", "查看 / 停止会话内进程"},
			{"reclaim / compact", "回收内存 / 整理空闲 Agent 上下文"},
			{"memory-status / memory-setup-script", "压缩交换区状态 / 管理员启用脚本"},
		}},
		Section{"层级、诊断与台账", []Entry{
			{"resolve SESSION", "将展示名或 ID 解析为唯一会话 ID"},
			{"children SESSION", "列出直接子会话"},
			{"parent <get|set|clear>", "查看或调整父子归属"},
			{"status [GROUP]", "查看会话与任务组状态"},
			{"info", "查看终端服务信息"},
			{"db <命令>", "管理会话台账（同 roami db）"},
		}},
		Section{"兼容短名与顶层入口", []Entry{
			{"nw / lw / kw", "window new / ls / kill 的兼容短名"},
			{"sp / split / kp", "pane split / kill 的兼容短名（sp -h 为左右分屏）"},
			{"swarm", "蜂群协作（推荐直接用 roami swarm）"},
			{"completion", "安装 Shell 补全（推荐直接用 roami completion）"},
		}},
	)
	p.Notes = []string{
		"仅提供业务命令，不转发原生 tmux 命令。",
		"SESSION / PARENT 可用会话 ID；自动化应保存稳定 ID。",
	}
	return p
}
