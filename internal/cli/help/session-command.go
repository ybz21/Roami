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
	}
	type spec struct {
		summary, args string
		options       []Entry
		examples      []Entry
		notes         []string
	}
	specs := map[string]spec{
		"ls":                  {"列出会话", "[--json] [--tree]", []Entry{{"--json", "输出 JSON"}, {"--tree", "按父子层级显示"}, {"--live --json", "读取当前存活会话；不可与 --tree 合用"}}, []Entry{{"roami session ls --tree", ""}}, nil},
		"new":                 {"新建会话", "[NAME] [选项]", []Entry{{"--dir PATH, -c PATH", "工作目录"}, {"--size WIDTHxHEIGHT", "终端尺寸"}, {"--detach, -d", "创建后不进入终端"}, {"--json", "输出 JSON，并保持分离"}, {"--no-reuse", "即使展示名相同也新建"}}, []Entry{{"roami session new build --dir . --detach", ""}}, nil},
		"fork":                {"从父会话派生子会话", "[PARENT] NAME [选项]", []Entry{{"PARENT", "父会话 ID 或名称；省略时使用当前会话"}, {"NAME", "子会话展示名（必填）"}, {"--dir PATH, -c PATH", "子会话工作目录；默认继承父会话"}, {"--detach, -d", "创建后不进入终端"}, {"--json", "输出 JSON，并保持分离"}}, []Entry{{"roami session fork review --detach", "从当前会话派生"}, {"roami session fork PARENT_ID review --dir . --detach --json", "指定父会话和目录"}}, []string{"继承父会话环境；不复制 Agent 对话、不启动 Agent、不创建 Git worktree。", "创建结果中的 session 是稳定 ID，label 是展示名。"}},
		"attach":              {"进入会话", "[SESSION]", nil, []Entry{{"roami session attach SESSION_ID", ""}}, []string{"省略 SESSION 时交互选择；别名 a。"}},
		"detach":              {"分离会话", "[SESSION]", nil, nil, []string{"省略 SESSION 时分离当前客户端；别名 d。"}},
		"kill":                {"关闭指定会话", "SESSION [--cascade] [--yes]", []Entry{{"--cascade", "同时关闭后代会话"}, {"--yes, -y", "跳过交互确认"}}, nil, []string{"默认保留子会话并调整归属；只关闭明确指定的资源。"}},
		"rename":              {"修改会话展示名", "SESSION NAME", nil, []Entry{{"roami session rename SESSION_ID review", ""}}, []string{"只修改展示名，会话 ID 保持不变。"}},
		"capture":             {"读取会话终端输出", "SESSION [--lines N]", []Entry{{"--lines N, -n N", "读取末尾行数（默认 200）"}}, []Entry{{"roami session capture SESSION_ID --lines 100", ""}}, nil},
		"send":                {"向普通会话发送文本", "SESSION TEXT", nil, []Entry{{`roami session send SESSION_ID "git status"`, ""}}, []string{"发送成功只表示文本已提交，仍需核对执行结果。", "受管任务通过 task_steer 或 roami swarm say 续接。"}},
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
		"nw":                  {"新建窗口", "[NAME]", nil, nil, nil},
		"lw":                  {"列出窗口", "", nil, nil, nil},
		"kw":                  {"关闭窗口", "[WINDOW]", nil, nil, nil},
		"sp":                  {"分割当前窗格", "[-h|-v]", []Entry{{"-h", "左右分割（业务参数，不是帮助）"}, {"-v", "上下分割"}}, []Entry{{"roami session sp -h", "左右分割"}, {"roami session sp --help", "查看帮助"}}, nil},
		"kp":                  {"关闭当前窗格", "[PANE]", nil, nil, nil},
		"status":              {"查看会话与任务组状态", "[GROUP] [--json]", nil, nil, nil},
		"info":                {"查看服务器信息", "[--json]", nil, nil, nil},
		"completion":          {"安装 Shell 补全", "", nil, nil, nil},
		"env":                 {"管理全局环境变量", "[ls] [--json]\n  roami session env set KEY=VALUE\n  roami session env rm KEY\n  roami session env clear\n  roami session env push [--preview] [--json]", nil, nil, nil},
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
