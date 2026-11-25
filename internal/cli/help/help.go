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
		Command: "roami session", Summary: "管理终端会话、窗口与分屏",
		Usage: []string{
			"roami session <命令> [参数]",
			"roami session <命令> -h",
			"roami session help --all",
		},
		Sections: []Section{
			{"会话管理", []Entry{
				{"ls", "列出会话（--tree 看层级，--json 输出 JSON）"},
				{"new [NAME]", "新建独立会话（默认进入终端，-d 后台创建）"},
				{"attach [SESSION[:WINDOW]]", "进入会话或指定窗口（别名 a；省略时交互选择）"},
				{"detach [SESSION]", "脱离当前会话（别名 d）"},
				{"rename SESSION NAME", "修改展示名，保留会话 ID"},
				{"kill SESSION", "关闭指定会话"},
			}},
			{"窗口与分屏（会话内部）", []Entry{
				{"window <new|ls|select|kill>", "管理会话内窗口（类似标签页）"},
				{"pane <ls|split|kill>", "管理窗口内分屏（--right 左右，--down 上下）"},
			}},
			{"读写与派生", []Entry{
				{"capture SESSION", "读取终端屏幕输出（支持 --window / --pane）"},
				{"send SESSION TEXT", "向普通会话提交文本或命令"},
				{"keys SESSION KEY...", "向会话发送按键"},
				{"fork [PARENT] NAME", "从父会话派生子会话（配套 parent / children）"},
			}},
			{"环境与运维", []Entry{
				{"env", "管理全局环境变量（ls / set / rm / push）"},
				{"pause / resume", "暂停 / 恢复会话进程"},
				{"processes / process-stop", "查看 / 停止会话内进程"},
				{"reclaim / compact", "回收内存 / 整理空闲 Agent 上下文"},
			}},
		},
		Examples: []Entry{
			{"roami session new dev", "新建并进入会话 dev"},
			{"roami session ls", "查看所有会话"},
			{"roami session window new dev logs", "在会话 dev 内新开窗口 logs"},
			{"roami session attach dev --window logs", "进入 dev 的 logs 窗口（简写 dev:logs）"},
			{"roami session pane split dev --right", "在 dev 当前窗口左右分屏"},
		},
		Notes: []string{
			"SESSION / PARENT 支持展示名或稳定 ID；自动化脚本应固定使用稳定 ID。",
			"进入原生终端后底部有状态栏提示：Ctrl+b m 打开交互菜单，Ctrl+b w 切换窗口/分屏，Ctrl+b d 脱离。",
			"查看全部命令（含 resolve / info / memory-* 及兼容短名 nw/lw/kw/sp/kp）：roami session help --all",
		},
		More: "roami session <命令> -h",
	}
}

func sessionAllPage() Page {
	p := sessionPage()
	p.Command = "roami session (全部命令)"
	p.Sections = append(p.Sections,
		Section{"层级、诊断与台账", []Entry{
			{"resolve SESSION", "将展示名或 ID 解析为唯一会话 ID"},
			{"children SESSION", "列出直接子会话"},
			{"parent <get|set|clear>", "查看或调整父子归属"},
			{"status [GROUP]", "查看会话与任务组状态"},
			{"info", "查看终端服务信息"},
			{"memory-status", "查看压缩交换区状态"},
			{"memory-setup-script", "输出压缩交换区管理员启用脚本"},
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
