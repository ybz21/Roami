package help

import "io"

func Show(_ string, w io.Writer) { _ = sessionPage().Render(w) }

func Command(command string, w io.Writer) bool {
	page, ok := sessionCommandPage(command)
	if ok {
		_ = page.Render(w)
	}
	return ok
}

func sessionPage() Page {
	return Page{
		Command: "roami session", Summary: "管理会话、终端与环境",
		Usage: []string{"roami session <命令> [参数]", "roami session <命令> --help"},
		Sections: []Section{
			{"常用命令", []Entry{
				{"ls", "列出会话；--tree 查看层级"}, {"new [NAME]", "新建会话"},
				{"attach [SESSION]", "进入会话；省略会话时交互选择（别名 a）"},
				{"detach [SESSION]", "分离会话（别名 d）"}, {"fork [PARENT] NAME", "从父会话派生子会话"},
				{"rename SESSION NAME", "修改展示名，保留会话 ID"}, {"kill SESSION", "关闭指定会话"},
			}},
			{"查看与输入", []Entry{
				{"capture SESSION", "读取终端输出"}, {"send SESSION TEXT", "向普通会话发送文本"},
				{"keys SESSION KEY...", "发送按键"}, {"resolve SESSION", "解析会话身份"},
				{"children SESSION", "列出直接子会话"}, {"parent", "查看或调整父子关系"}, {"status", "查看会话与任务组状态"},
			}},
			{"运行管理", []Entry{
				{"pause / resume", "暂停 / 继续指定会话"}, {"reclaim / compact", "回收内存 / 整理 Agent 上下文"},
				{"processes / process-stop", "查看 / 停止指定进程"}, {"memory-status", "查看压缩交换区状态"},
				{"memory-setup-script", "输出管理员启用脚本"},
			}},
			{"终端与环境", []Entry{
				{"nw / lw / kw", "新建 / 列出 / 关闭窗口"}, {"sp / kp", "分割 / 关闭窗格"},
				{"env", "管理全局环境变量"}, {"info", "查看服务器信息"},
				{"completion", "安装 Shell 补全"}, {"swarm", "蜂群协作（同 roami swarm）"},
			}},
		},
		Examples: []Entry{{"roami session ls --tree", ""}, {"roami session fork PARENT_ID review --detach", ""}, {"roami session fork -h", "查看参数与示例"}},
		Notes:    []string{"SESSION / PARENT 可用会话 ID；自动化应保存稳定 ID。", "仅提供业务命令，不转发原生 tmux 命令。"},
		More:     "roami session <命令> -h",
	}
}
