package help

func sessionCommandPage(command string) (Page, bool) {
	canonical := command
	switch command {
	case "a":
		canonical = "attach"
	case "d":
		canonical = "detach"
	case "split":
		canonical = "sp"
	case "env list":
		canonical = "env ls"
	case "env del", "env delete":
		canonical = "env rm"
	case "window list":
		canonical = "window ls"
	case "window rm", "window close":
		canonical = "window kill"
	case "window switch":
		canonical = "window select"
	case "pane list":
		canonical = "pane ls"
	case "pane rm", "pane close":
		canonical = "pane kill"
	}
	type spec struct {
		summary, args string
		options       []Entry
		examples      []Entry
		notes         []string
	}
	specs := map[string]spec{
		"ls": {"列出会话", "[--backend native|tmux] [--json] [--tree]", []Entry{
			{"--backend native|tmux", "只列出指定终端引擎的会话；省略时合并展示"},
			{"--json", "输出 JSON"},
			{"--tree", "按父子层级显示"},
			{"--live --json", "读取当前存活会话；不可与 --tree 合用"},
		}, []Entry{{"roami session ls", ""}, {"roami session ls --tree", ""}, {"roami session ls --backend native", ""}}, nil},

		"new": {"新建独立会话", "[NAME] [选项]", []Entry{
			{"--backend native|tmux", "选择终端引擎（native 为原生 PTY，全平台默认启用；Unix 可用 --backend tmux 或 ROAMI_NATIVE_TERMINAL=0 回退 tmux）"},
			{"--dir PATH, -c PATH", "工作目录"},
			{"--size WIDTHxHEIGHT", "终端初始尺寸"},
			{"--detach, -d", "后台创建，不进入终端"},
			{"--json", "输出 JSON，并保持分离"},
			{"--no-reuse", "即使展示名相同也强制新建"},
			{"--kind roami --task TEXT", "创建 Roami 托管任务会话，返回 roami: 会话 ID"},
			{"--model ID|auto", "托管任务会话使用的网关模型"},
			{"--free-only", "托管任务会话仅使用免费路由"},
			{"--key KEY", "托管任务会话的幂等键"},
		}, []Entry{
			{"roami session new dev", "新建并进入会话 dev"},
			{"roami session new build --dir . --detach", "后台创建会话"},
			{"roami session new --backend native dev", "显式使用原生 PTY 引擎创建"},
		}, nil},

		"fork": {"从父会话派生子会话", "[PARENT] NAME [选项]", []Entry{
			{"PARENT", "父会话 ID 或名称；省略时使用当前会话"},
			{"NAME", "子会话展示名（必填）"},
			{"--dir PATH, -c PATH", "子会话工作目录；默认继承父会话"},
			{"--detach, -d", "创建后不进入终端"},
			{"--json", "输出 JSON，并保持分离"},
		}, []Entry{
			{"roami session fork review --detach", "从当前会话派生"},
			{"roami session fork PARENT_ID review --dir . --detach --json", "指定父会话和目录"},
		}, []string{"继承父会话环境；不复制 Agent 对话、不启动 Agent、不创建 Git worktree。", "创建结果中的 session 是稳定 ID，label 是展示名。"}},

		"attach": {"进入会话或指定窗口", "[SESSION[:WINDOW]] [--window WINDOW] [--pane PANE_ID]", []Entry{
			{"--window WINDOW, -w WINDOW", "进入会话内的指定窗口（支持窗口名、窗口 ID 或 1 开始的序号）"},
			{"--pane ID, -p ID", "进入原生会话中的指定分屏窗格"},
		}, []Entry{
			{"roami session attach dev", "进入会话 dev 的当前活跃窗口"},
			{"roami session attach dev --window logs", "直接进入 dev 内的 logs 窗口"},
			{"roami session a dev:2", "简写：进入 dev 的第 2 个窗口"},
		}, []string{
			"省略 SESSION 时交互选择；别名 a。",
			"进入原生终端后，按 F2（或 Ctrl+b 空格）即可打开中文菜单，方向键操作分屏、切窗口、放后台。",
			"也支持常用直达键：Ctrl+b |/-（左右/上下分屏）、Ctrl+b Tab/方向键（切窗格）、Ctrl+b c（新窗口）、Ctrl+b d（放后台）。",
		}},

		"detach": {"脱离当前会话", "[SESSION]", nil, nil, []string{"省略 SESSION 时脱离当前客户端；别名 d。"}},
		"kill":   {"关闭指定会话", "SESSION [--cascade] [--yes]", []Entry{{"--cascade", "同时关闭后代会话"}, {"--yes, -y", "跳过交互确认"}}, nil, []string{"默认保留子会话并调整归属；只关闭明确指定的资源。"}},
		"rename": {"修改会话展示名", "SESSION NAME", nil, []Entry{{"roami session rename SESSION_ID review", ""}}, []string{"只修改展示名，会话 ID 保持不变。"}},

		"window": {"管理会话内窗口（标签页）", "<new|ls|select|kill> [参数]", []Entry{
			{"new [SESSION] [NAME]", "在会话内新建窗口（--attach 可直接进入）"},
			{"ls [SESSION]", "列出该会话的全部窗口与分屏"},
			{"select [SESSION] WINDOW", "切换会话的当前活跃窗口（按名称、ID 或序号）"},
			{"kill [SESSION] [WINDOW]", "关闭指定窗口（省略 WINDOW 时关当前窗口）"},
		}, []Entry{
			{"roami session window new dev logs", "在会话 dev 内新开窗口 logs"},
			{"roami session window ls dev", "查看 dev 的所有窗口"},
			{"roami session window select dev logs", "将 dev 的活跃窗口切换到 logs"},
			{"roami session attach dev:logs", "直接进入 dev 的 logs 窗口"},
		}, []string{"窗口归属于某个会话；进入会话后也可按 Ctrl+b w / Ctrl+b m 在终端内直接切换。"}},
		"window new": {"在会话内新建窗口", "[SESSION] [NAME] [--dir PATH] [--attach]", []Entry{
			{"--dir PATH, -c PATH", "新窗口工作目录（默认继承会话目录）"},
			{"--attach, -a", "创建后立即进入该窗口"},
		}, []Entry{
			{"roami session window new dev logs", "在 dev 内新开窗口 logs"},
			{"roami session window new dev logs --attach", "新开窗口并直接进入"},
		}, nil},
		"window ls": {"列出会话内的窗口", "[SESSION]", nil, []Entry{{"roami session window ls dev", ""}}, nil},
		"window select": {"切换会话的活跃窗口", "[SESSION] WINDOW", nil, []Entry{
			{"roami session window select dev logs", "按窗口名切换"},
			{"roami session window select dev 2", "按序号切换"},
		}, []string{"切换后，后续 attach 或 Web 端打开该会话都会落到此窗口。"}},
		"window kill": {"关闭会话内的窗口", "[SESSION] [WINDOW]", nil, []Entry{
			{"roami session window kill dev logs", "按窗口名关闭"},
			{"roami session window kill dev w-2", "按窗口 ID 关闭"},
		}, nil},

		"pane": {"管理窗口内窗格分屏", "<ls|split|kill> [参数]", []Entry{
			{"ls [SESSION]", "列出会话内所有窗格（可用 --window 过滤）"},
			{"split [SESSION] [--right|--down]", "切分窗格（--right 左右分屏，--down 上下分屏）"},
			{"kill [SESSION] [PANE]", "关闭指定窗格"},
		}, []Entry{
			{"roami session pane split dev --right", "在 dev 当前窗口左右分屏"},
			{"roami session pane split dev --down --window logs", "在 dev 的 logs 窗口上下分屏"},
			{"roami session pane ls dev", "查看 dev 内的全部窗格"},
		}, []string{"进入终端后也可直接按 Ctrl+b %（左右分屏）、Ctrl+b \"（上下分屏）、Ctrl+b o（切窗格）。"}},
		"pane ls": {"列出会话内窗格", "[SESSION] [--window WINDOW]", []Entry{
			{"--window WINDOW, -w WINDOW", "只列出指定窗口内的窗格"},
		}, []Entry{{"roami session pane ls dev", ""}}, nil},
		"pane split": {"分割窗格", "[SESSION] [--right|--down] [--window WINDOW] [--pane PANE] [--dir PATH]", []Entry{
			{"--right, --horizontal, -H", "左右分屏（默认）"},
			{"--down, --vertical, -V", "上下分屏"},
			{"--window WINDOW, -w WINDOW", "指定要切分的窗口"},
			{"--pane ID, -p ID", "指定要切分的窗格"},
			{"--dir PATH, -c PATH", "新窗格的工作目录"},
		}, []Entry{
			{"roami session pane split dev --right", "左右分屏"},
			{"roami session pane split dev --down", "上下分屏"},
		}, nil},
		"pane kill": {"关闭窗格", "[SESSION] [PANE] [--pane PANE]", []Entry{
			{"--pane ID, -p ID", "指定要关闭的窗格 ID"},
		}, []Entry{{"roami session pane kill dev p-2", ""}}, nil},

		"capture": {"读取会话终端输出", "SESSION [--lines N] [--window WINDOW] [--pane PANE_ID]", []Entry{
			{"--lines N, -n N", "读取末尾行数（默认 200）"},
			{"--window WINDOW, -w WINDOW", "抓取原生会话中的指定窗口"},
			{"--pane ID, -p ID", "抓取原生会话中的指定分屏窗格"},
			{"--history, -S", "包含滚回历史"},
		}, []Entry{{"roami session capture SESSION_ID --lines 100", ""}}, nil},

		"send":                {"向普通会话发送文本", "SESSION TEXT", nil, []Entry{{`roami session send SESSION_ID "git status"`, ""}}, []string{"普通文本发送成功只表示输入已提交。配对的互审消息会排队等待对端就绪。", "受管任务通过 task_steer 或 roami swarm say 续接。"}},
		"keys":                {"向会话发送按键", "SESSION KEY...", nil, []Entry{{"roami session keys SESSION_ID Down Enter", ""}}, []string{"只接受具名按键或单个字母数字；文本输入使用 send。"}},
		"resolve":             {"解析会话身份", "SESSION [--strict] [--json]", []Entry{{"--strict", "同名时返回错误，不自动选择"}, {"--json", "输出 JSON"}}, []Entry{{"roami session resolve review --strict --json", ""}}, nil},
		"children":            {"列出直接子会话", "SESSION [--json]", nil, nil, nil},
		"parent":              {"查看或调整父子关系", "get CHILD\n  roami session parent set CHILD PARENT\n  roami session parent clear CHILD", nil, []Entry{{"roami session parent get SESSION_ID", ""}}, nil},
		"pause":               {"暂停会话", "SESSION [--json]", nil, nil, []string{"保留进程与终端。"}},
		"resume":              {"继续会话", "SESSION [--json]", nil, nil, nil},
		"reclaim":             {"回收会话内存", "SESSION [--json]", nil, nil, nil},
		"compact":             {"整理空闲 Agent 上下文", "SESSION [--json]", nil, nil, nil},
		"processes":           {"查看会话进程树与内存", "SESSION [--json]", nil, nil, nil},
		"process-stop":        {"停止指定会话进程", "SESSION PID START [--force] [--json]", []Entry{{"PID / START", "使用 processes 返回的进程 ID 与启动标识"}, {"--force", "强制结束指定进程"}}, nil, nil},
		"memory-status":       {"查看压缩交换区状态", "", nil, nil, nil},
		"memory-setup-script": {"输出压缩交换区启用脚本", "", nil, nil, []string{"输出脚本供管理员检查执行；此命令本身不启用交换区。"}},

		"nw": {"新建窗口（window new 的兼容短名）", "[SESSION] [NAME]", nil, []Entry{{"roami session window new dev logs", "推荐写法"}}, []string{"推荐使用 roami session window new。"}},
		"lw": {"列出窗口（window ls 的兼容短名）", "[SESSION]", nil, []Entry{{"roami session window ls dev", "推荐写法"}}, []string{"推荐使用 roami session window ls。"}},
		"kw": {"关闭窗口（window kill 的兼容短名）", "[SESSION] [WINDOW]", nil, []Entry{{"roami session window kill dev logs", "推荐写法"}}, []string{"推荐使用 roami session window kill。"}},
		"sp": {"分割窗格（pane split 的兼容短名）", "[SESSION] [-h|-v] [--pane PANE_ID]", []Entry{{"-h", "左右分割（兼容参数，不是帮助；查看帮助请用 --help）"}, {"-v", "上下分割"}, {"--pane ID, -p ID", "指定要切分的原生窗格"}}, []Entry{{"roami session pane split dev --right", "推荐写法"}, {"roami session sp dev -h", "兼容短名"}}, []string{"推荐使用 roami session pane split --right / --down。"}},
		"kp": {"关闭窗格（pane kill 的兼容短名）", "[SESSION] [PANE]", []Entry{{"--pane ID, -p ID", "指定要关闭的原生窗格"}}, []Entry{{"roami session pane kill dev p-2", "推荐写法"}}, []string{"推荐使用 roami session pane kill。"}},

		"status":     {"查看会话与任务组状态", "[GROUP] [--json]", nil, nil, nil},
		"info":       {"查看服务器信息", "[--json]", nil, nil, nil},
		"completion": {"安装 Shell 补全", "", nil, nil, nil},
		"env":        {"管理全局环境变量", "[ls] [--json]\n  roami session env set KEY=VALUE\n  roami session env rm KEY\n  roami session env clear\n  roami session env push [--preview] [--json]", nil, nil, nil},
	}
	for name, item := range map[string]spec{
		"parent get":    {summary: "查看父会话", args: "CHILD"},
		"parent set":    {summary: "设置父会话", args: "CHILD PARENT"},
		"parent clear":  {summary: "清除父会话归属", args: "CHILD"},
		"env ls":        {summary: "列出全局环境变量", args: "[--json]"},
		"env set":       {summary: "设置全局环境变量", args: "KEY=VALUE", examples: []Entry{{"roami session env set EDITOR=vim", ""}}},
		"env rm":        {summary: "删除全局环境变量", args: "KEY"},
		"env clear":     {summary: "清空全局环境变量"},
		"env push":      {summary: "向会话同步全局环境变量", args: "[--preview] [--json]", notes: []string{"--preview 只查看将要同步的内容。"}},
		"db":            {summary: "管理会话台账", args: "<命令>", options: []Entry{{"status / migrate", "查看 / 迁移台账"}, {"backup", "备份台账"}, {"history", "查看已结束会话"}, {"restore / revive", "恢复台账会话"}, {"set-home / link-agent", "登记目录 / 关联 Agent 对话"}}},
		"db status":     {summary: "查看台账状态", args: "[--json]"},
		"db migrate":    {summary: "迁移会话台账", args: "[--json]"},
		"db backup":     {summary: "备份会话台账", args: "[--out PATH] [--json]"},
		"db history":    {summary: "查看已结束会话", args: "[--limit N] [--json]"},
		"db restore":    {summary: "从台账恢复会话", args: "SESSION [--json]"},
		"db revive":     {summary: "恢复休眠会话", args: "SESSION [--json]"},
		"db set-home":   {summary: "登记会话目录", args: "SESSION PATH"},
		"db link-agent": {summary: "关联 Agent 对话", args: "SESSION CONVERSATION_ID [KIND]"},
	} {
		specs[name] = item
	}

	s, ok := specs[canonical]
	if !ok {
		return Page{}, false
	}
	usage := "roami session " + canonical
	if s.args != "" {
		usage += " " + s.args
	}
	page := Page{Command: "roami session " + canonical, Summary: s.summary, Usage: []string{usage}, Examples: s.examples, Notes: s.notes, More: "roami session --help"}
	if len(page.Examples) == 0 {
		page.Examples = []Entry{{usage, ""}}
	}
	if len(s.options) > 0 {
		page.Sections = []Section{{"参数", s.options}}
	}
	return page, true
}
