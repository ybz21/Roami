package main

import (
	"flag"
	"fmt"
	"os"
	"slices"
	"strings"

	clihelp "github.com/ybz21/Roami/internal/cli/help"
)

type commandGuide struct {
	summary, syntax, example, options string
	notes                             []string
}

var commandGuides = map[string]commandGuide{
	"version":                            {"查看版本", "", "roami version", "", nil},
	"completion":                         {"输出 Shell 补全脚本", "", "roami completion", "", []string{"输出 bash/zsh 补全脚本；会话补全安装使用 roami session completion。"}},
	"db history":                         {"查看已结束会话", "[--json]", "roami db history --json", "json", nil},
	"db revive":                          {"恢复休眠会话", "SESSION [--json]", "roami db revive SESSION_ID --json", "json", nil},
	"db set-home":                        {"登记会话目录", "SESSION PATH", "roami db set-home SESSION_ID /path/to/project", "", nil},
	"db link-agent":                      {"关联 Agent 对话", "SESSION CONVERSATION_ID [KIND]", "roami db link-agent SESSION_ID CONVERSATION_ID codex", "", nil},
	"chrome url":                         {"读取当前页面网址", "[--target TAB_ID]", "roami chrome url --target TAB_ID", "", nil},
	"chrome title":                       {"读取当前页面标题", "[--target TAB_ID]", "roami chrome title --target TAB_ID", "", nil},
	"plugin config":                      {"查看或修改插件配置", "PLUGIN_ID [set KEY VALUE | unset KEY]", "roami plugin config PLUGIN_ID", "", nil},
	"project ls":                         {"列出项目", "[--json] [--server URL]", "roami project ls --json", "server json", nil},
	"project show":                       {"查看项目详情", "PROJECT_ID [--json] [--server URL]", "roami project show PROJECT_ID --json", "server json", nil},
	"project sessions":                   {"查看项目会话", "PROJECT_ID [--json] [--server URL]", "roami project sessions PROJECT_ID --json", "server json", nil},
	"project create":                     {"登记目录或克隆项目", "[PATH] [选项]", "roami project create . --name demo", "server json name clone provision-key base-dir", []string{"省略 PATH 时必须提供 --provision-key；--base-dir 指定新项目的父目录。"}},
	"project prefs":                      {"修改项目偏好", "PROJECT_ID [选项]", "roami project prefs PROJECT_ID --pinned true", "server json name pinned agent base", nil},
	"project activity":                   {"查看项目活动", "PROJECT_ID [--json] [--server URL]", "roami project activity PROJECT_ID --json", "server json", nil},
	"project remove":                     {"移除项目登记", "PROJECT_ID [--json] [--server URL]", "roami project remove PROJECT_ID", "server json", nil},
	"auth login":                         {"登录 Roami 服务", "[--server URL] [--stdin] [--json]", "roami auth login --server https://localhost:13579", "server stdin json", []string{"默认交互输入密码；脚本使用 --stdin 从标准输入读取 password/code JSON。"}},
	"auth logout":                        {"退出登录", "[--server URL] [--json]", "roami auth logout", "server json", nil},
	"auth status":                        {"查看登录状态", "[--server URL] [--json]", "roami auth status", "server json", nil},
	"db status":                          {"查看数据库状态", "[--json]", "roami db status --json", "json", nil},
	"db migrate":                         {"迁移数据库", "[--layout --dry-run | --layout --offline | --recover] [--json]", "roami db migrate --layout --dry-run", "layout dry-run offline recover json", []string{"正式布局迁移前须停止旧版本写入者；先用 --dry-run 只读核对。"}},
	"db backup":                          {"备份数据库", "[PATH] [--json]", "roami db backup /tmp/roami-backup", "json", nil},
	"db restore":                         {"恢复数据库备份集", "PATH [--json]", "roami db restore /tmp/roami-backup", "json", []string{"只能恢复到空实例。"}},
	"agent setup":                        {"安装 Agent 运行时依赖", "[--runtime-dir PATH]", "roami agent setup", "runtime-dir", nil},
	"agent init":                         {"初始化 Agent 运行时", "[--runtime-dir PATH]", "roami agent init", "runtime-dir", nil},
	"agent serve":                        {"启动 Agent 运行时", "[--runtime-dir PATH]", "roami agent serve", "runtime-dir", []string{"使用私有 Unix socket；公开 HTTP/SSE 通过 roami server 提供。"}},
	"agent status":                       {"查看 Agent 状态", "[--json]", "roami agent status", "json", nil},
	"agent installed-status":             {"查看本机 Agent 安装状态", "", "roami agent installed-status", "", nil},
	"agent prepare-upgrade":              {"暂停受管运行时以准备升级", "", "roami agent prepare-upgrade", "", nil},
	"agent resume-upgrade":               {"恢复升级后的受管运行时", "", "roami agent resume-upgrade", "", nil},
	"agent conversations":                {"列出 Agent 对话", "[--json]", "roami agent conversations", "json", nil},
	"agent identity":                     {"查看对话身份", "--conversation ID", "roami agent identity --conversation CONVERSATION_ID", "conversation json", nil},
	"agent new":                          {"新建 Agent 对话", "[--title TEXT] [--key KEY]", "roami agent new --title review", "title key json", nil},
	"agent send":                         {"向对话发送消息", "--conversation ID (--text TEXT | --file PATH) [--key KEY]", "roami agent send --conversation CONVERSATION_ID --text '检查项目'", "conversation text file key json", nil},
	"agent wake":                         {"从外部唤醒项目对话", "--conversation ID --project ID --key KEY (--text TEXT | --file PATH)", "roami agent wake --conversation CONVERSATION_ID --project PROJECT_ID --key wake-1 --text '检查进展'", "conversation project key text file json", nil},
	"agent history":                      {"读取对话历史", "--conversation ID [--limit N] [--before CURSOR] [--branch ID]", "roami agent history --conversation CONVERSATION_ID --limit 20", "conversation limit before branch json", nil},
	"agent report":                       {"回报任务结果", "--task ID --run ID --revision N --file RESULT.json", "roami agent report --task TASK_ID --run RUN_ID --revision 1 --file result.json", "task run revision file json", nil},
	"agent reply":                        {"向来源 Main 回报会话任务", "--dispatch ID --file RESULT.json", "roami agent reply --dispatch DISPATCH_ID --file result.json", "dispatch file json", nil},
	"agent notify":                       {"向对话发送主动通知", "--conversation ID --source SOURCE --key KEY (--text TEXT | --file PATH)", "roami agent notify --conversation CONVERSATION_ID --source cli --key note-1 --text '检查完成'", "conversation source key text file json", nil},
	"agent steer":                        {"续接受管任务", "--task ID --revision N --key KEY (--text TEXT | --file PATH)", "roami agent steer --task TASK_ID --revision 1 --key steer-1 --text '补充测试'", "task revision key text file json", nil},
	"agent steering":                     {"查看任务续接状态", "--task ID --operation ID", "roami agent steering --task TASK_ID --operation OPERATION_ID", "task operation json", nil},
	"agent capability list":              {"搜索已安装能力", "[--kind KIND] [--query TEXT] [--limit N] [--offset N]", "roami agent capability list --query browser", "kind query limit offset json", nil},
	"agent capability show":              {"查看能力详情", "NAME", "roami agent capability show skill_read", "json", nil},
	"agent capability read":              {"读取任务 Skill", "SKILL --context FILE [--reference PATH]", "roami agent capability read SKILL_NAME --context context.json", "context reference call json", nil},
	"agent capability call":              {"调用已授权能力", "NAME --input JSON [--context FILE] [--turn ID] [--call ID]", "roami agent capability call CAPABILITY --input '{}' --context context.json", "input context turn call json", []string{"需当前运行的工具上下文；未知结果只能用原调用 ID 与原参数恢复，不可重复执行。"}},
	"agent reminder ls":                  {"查看提醒", "", "roami agent reminder ls", "json", nil},
	"agent reminder add":                 {"创建提醒", "--conversation ID --key KEY --text TEXT [时间选项]", "roami agent reminder add --conversation CONVERSATION_ID --key remind-1 --text '检查进展' --after-seconds 3600", "conversation key text file kind after-seconds when-ms daily-at timezone json", []string{"--after-seconds、--when-ms、--daily-at 必须且只能选择一项。", "--kind daily_brief 必须使用 --daily-at。"}},
	"agent reminder cancel":              {"取消提醒", "--id ID", "roami agent reminder cancel --id REMINDER_ID", "id json", nil},
	"agent notification-preferences get": {"查看通知偏好", "", "roami agent notification-preferences get", "json", nil},
	"agent notification-preferences set": {"替换通知偏好", "--file SETTINGS.json", "roami agent notification-preferences set --file settings.json", "file json", []string{"完整替换设置；先用 get 读取当前值。"}},
	"agent control ls":                   {"查看任务资源", "--task ID", "roami agent control ls --task TASK_ID", "task json", nil},
	"agent control show":                 {"查看资源控制状态", "--resource ID", "roami agent control show --resource RESOURCE_ID", "resource json", nil},
	"agent control pause":                {"暂停资源输入", "--resource ID", "roami agent control pause --resource RESOURCE_ID", "resource json", []string{"实际停止输入并释放租约后才返回 takeoverReady；暂停中使用 show 核对。"}},
	"agent control resume":               {"继续资源输入", "--resource ID", "roami agent control resume --resource RESOURCE_ID", "resource json", nil},
	"agent trace":                        {"查看执行追踪", "(--turn ID | --task ID) [--format json|chrome]", "roami agent trace --task TASK_ID --format json", "turn task format", nil},
	"speech transcribe":                  {"识别 WAV 音频", "--file AUDIO.wav --file-root ROOT --expected-file-sha256 SHA [--server URL] [--json]", "roami speech transcribe --file /tmp/audio.wav --file-root /tmp --expected-file-sha256 SHA --json", "file file-root expected-file-sha256 server json", []string{"沿用节点登录与语音配置；只上传一次，不自动重试。回执含原始响应与音频摘要；识别结果不表示内容已获批准。"}},
	"project okr show":                   {"查看目标工作区", "PROJECT_ID [--server URL] [--json]", "roami project okr show PROJECT_ID --json", "server file json", nil},
	"project okr save":                   {"保存目标工作区", "PROJECT_ID --file JSON|- [--server URL] [--json]", "roami project okr save PROJECT_ID --file request.json --json", "server file json", []string{"写入需当前修订；冲突时重新读取，未知结果先核对，不自动重试。"}},
	"project okr sync":                   {"同步目标文件", "PROJECT_ID --file JSON|- [--server URL] [--json]", "roami project okr sync PROJECT_ID --file request.json --json", "server file json", []string{"写入需当前修订；冲突时重新读取，未知结果先核对，不自动重试。"}},
	"project okr memory":                 {"修改项目记忆", "PROJECT_ID --file JSON|- [--server URL] [--json]", "roami project okr memory PROJECT_ID --file request.json --json", "server file json", []string{"写入需当前修订；冲突时重新读取，未知结果先核对，不自动重试。"}},
	"project okr record":                 {"记录目标观测值", "PROJECT_ID --file JSON|- [--server URL] [--json]", "roami project okr record PROJECT_ID --file request.json --json", "server file json", []string{"写入需当前修订；冲突时重新读取，未知结果先核对，不自动重试。"}},
	"project okr collect":                {"提交采集批次", "PROJECT_ID --file JSON|- [--server URL] [--json]", "roami project okr collect PROJECT_ID --file request.json --json", "server file json", []string{"写入需当前修订；冲突时重新读取，未知结果先核对，不自动重试。"}},
	"project okr review":                 {"提交目标复盘", "PROJECT_ID --file JSON|- [--server URL] [--json]", "roami project okr review PROJECT_ID --file request.json --json", "server file json", []string{"写入需当前修订；冲突时重新读取，未知结果先核对，不自动重试。"}},
	"agent install-bundle":               {"安装 Agent 运行包", "--archive PATH --destination PATH [选项]", "roami agent install-bundle --archive release.tgz --destination /tmp/release", "archive destination expected-version activate check bin-dir", nil},
	"agent install-probe":                {"检查 Agent 安装", "--runtime-dir PATH", "roami agent install-probe --runtime-dir /tmp/runtime", "runtime-dir", nil},
	"agent mcp install":                  {"安装独立 MCP 服务", "[--runtime-dir PATH]", "roami agent mcp install", "runtime-dir home-root data-root socket", []string{"独立 MCP 服务；在 Agent 环境中配置 ROAMI_MCP_SOCKET。"}},
	"agent mcp serve":                    {"启动独立 MCP 服务", "[--runtime-dir PATH]", "roami agent mcp serve", "runtime-dir home-root data-root socket", nil},
	"agent mcp status":                   {"查看 MCP 服务状态", "[--socket PATH]", "roami agent mcp status", "home-root data-root socket", nil},
	"agent gateway settings":             {"查看模型网关设置", "", "roami agent gateway settings", "", nil},
	"agent gateway usage":                {"查看模型网关用量", "[--days N]", "roami agent gateway usage --days 7", "days", nil},
	"agent gateway configure":            {"替换模型计价与每日额度配置", "--file JSON|-", "roami agent gateway configure --file settings.json", "file", nil},
	"agent gateway reconcile":            {"核对未知调用费用", "--call ID --file JSON|-", "roami agent gateway reconcile --call CALL_ID --file receipt.json", "call file", nil},
	"agent gateway binding":              {"查看网关绑定", "[--data-root PATH]", "roami agent gateway binding", "data-root", nil},
	"agent execution catalog":            {"查看已安装执行器", "[--commands NAMES]", "roami agent execution catalog --commands codex,claude", "commands", []string{"只读检查安装与跟踪能力；不证明鉴权可用或额度充足。"}},
	"agent execution context":            {"查看当前执行上下文", "[--json]", "roami agent execution context --json", "json", []string{"只读当前原生运行；不授予发布权限。"}},
	"agent execution launch":             {"启动执行器任务", "--file SPEC.json", "roami agent execution launch --file SPEC.json", "file", []string{"SPEC.json 中 persistent=true 保留交互会话，直到显式 close；默认是一次性执行。", "projectId 创建新的项目 worktree；同时指定 workspaceId 时复用已登记工作区，不 fetch/reset。", "续接已有 sessionId 需可验证的生命周期回调。"}},
	"agent execution send-message":       {"投递执行器消息", "--file JSON|-", "roami agent execution send-message --file JSON|-", "file", []string{"回执只表示投递结果，仍需核对执行与交付结果。"}},
	"agent execution status":             {"查看执行器任务状态", "--key LAUNCH_KEY", "roami agent execution status --key LAUNCH_KEY", "key", nil},
	"agent execution cancel":             {"取消执行器任务", "--key LAUNCH_KEY", "roami agent execution cancel --key LAUNCH_KEY", "key", nil},
	"agent execution close":              {"关闭执行器任务", "--key LAUNCH_KEY", "roami agent execution close --key LAUNCH_KEY", "key", nil},
	"agent execution cleanup":            {"清理执行器任务资源", "--key LAUNCH_KEY", "roami agent execution cleanup --key LAUNCH_KEY", "key", nil},
	"agent execution run":                {"运行执行器任务", "--file SPEC.json", "roami agent execution run --file SPEC.json", "file", nil},
	"agent execution hold":               {"管理原生工作区租约", "--file JSON|-", "roami agent execution hold --file JSON|-", "file", nil},
	"agent execution reconcile-native":   {"核对原生停止证据", "--key LAUNCH_KEY --file JSON|-", "roami agent execution reconcile-native --key LAUNCH_KEY --file JSON|-", "key file", nil},
	"agent execution reconcile-session":  {"核对会话输入变更与停止证据", "--key LAUNCH_KEY", "roami agent execution reconcile-session --key LAUNCH_KEY", "key", nil},
	"agent execution hook-config":        {"输出执行器生命周期配置", "--executor codex|claude", "roami agent execution hook-config --executor codex|claude", "executor", nil},
	"agent execution event":              {"接收生命周期事件", "--executor codex|claude --file JSON|-", "roami agent execution event --executor codex|claude --file JSON|-", "executor file tmux-bin", nil},
	"agent execution notify":             {"转发 Codex 完成通知", "--executor codex --chain PATH --notification JSON", "roami agent execution notify --executor codex --chain PATH --notification JSON", "executor chain notification", nil},
	"agent capability market sources":    {"查看能力市场来源", "", "roami agent capability market sources", "json", nil},
	"agent capability market search":     {"搜索能力市场", "--input JSON [--context FILE] [--call ID]", "roami agent capability market search --input '{\"source\":\"skills-sh\",\"query\":\"find-skills\"}'", "input context call json", nil},
	"agent capability market preview":    {"预览能力安装选项", "--input JSON [--context FILE] [--call ID]", "roami agent capability market preview --input '{\"source\":\"skills-sh\",\"id\":\"OWNER/REPO/SKILL\",\"version\":\"\"}'", "input context call json", []string{"预览固定下载选项，有效期十分钟；安装是单独操作。"}},
	"agent capability market install":    {"安装已预览能力", "--input JSON [--context FILE] [--call ID]", "roami agent capability market install --input '{\"previewId\":\"PREVIEW_ID\",\"option\":0}'", "input context call json", []string{"不覆盖已有名称；MCP 初始不连接，npm CLI 首次调用才下载固定包。"}},
	"chrome setup":                       {"安装或更新浏览器自动化依赖", "", "roami chrome setup", "", nil},
	"chrome goto":                        {"打开网址", "URL [--wait-until load|domcontentloaded|commit]", "roami chrome goto https://example.com --target TAB_ID", "", nil},
	"chrome click":                       {"点击元素", "SELECTOR", "roami chrome click \"button.submit\" --target TAB_ID", "", nil},
	"chrome fill":                        {"填写表单", "SELECTOR TEXT", "roami chrome fill \"#name\" \"demo\" --target TAB_ID", "", nil},
	"chrome type":                        {"逐字输入", "SELECTOR TEXT", "roami chrome type \"#name\" \"demo\" --target TAB_ID", "", nil},
	"chrome upload":                      {"选择本机文件", "SELECTOR ABSOLUTE_PATH --target TAB_ID [选项]", "roami chrome upload \"input[type=file]\" /tmp/report.pdf --target TAB_ID", "", nil},
	"chrome press":                       {"发送按键", "[SELECTOR] KEY", "roami chrome press Enter --target TAB_ID", "", nil},
	"chrome text":                        {"读取可见文本", "[SELECTOR]", "roami chrome text body --target TAB_ID", "", nil},
	"chrome html":                        {"读取页面 HTML", "[SELECTOR]", "roami chrome html --target TAB_ID", "", nil},
	"chrome attr":                        {"读取元素属性", "SELECTOR ATTRIBUTE", "roami chrome attr a href --target TAB_ID", "", nil},
	"chrome eval":                        {"执行页面 JavaScript", "SCRIPT", "roami chrome eval \"document.title\" --target TAB_ID", "", nil},
	"chrome wait":                        {"等待元素出现", "SELECTOR", "roami chrome wait \"#result\" --target TAB_ID", "", nil},
	"chrome screenshot":                  {"保存页面截图", "[PATH] [选项]", "roami chrome screenshot /tmp/page.png --target TAB_ID --full", "", nil},
	"chrome pdf":                         {"导出页面 PDF", "[PATH]", "roami chrome pdf /tmp/page.pdf --target TAB_ID", "", nil},
	"chrome sleep":                       {"休眠后台标签页", "--target TAB_ID --no-focus", "roami chrome sleep --target TAB_ID --no-focus", "", nil},
	"chrome wake":                        {"唤醒标签页", "--target TAB_ID", "roami chrome wake --target TAB_ID", "", nil},
	"chrome new":                         {"新建标签页", "[URL] [--origin human|agent]", "roami chrome new https://example.com --origin human", "", nil},
	"chrome capabilities":                {"查看驱动能力与浏览器身份", "", "roami chrome capabilities", "", nil},
	"chrome observe":                     {"观察页面状态", "--target TAB_ID [--screenshot PATH]", "roami chrome observe --target TAB_ID", "", nil},
	"chrome tabs":                        {"列出标签页与稳定 ID", "", "roami chrome tabs", "", nil},
	"chrome close":                       {"关闭标签页", "[--target TAB_ID] [--no-focus] [--only-if-background]", "roami chrome close --target TAB_ID", "", nil},
	"chrome record start":                {"开始录制画面", "PATH.mp4 [--target TAB_ID]", "roami chrome record start /tmp/demo.mp4 --target TAB_ID", "", nil},
	"chrome record stop":                 {"停止录制并保存", "", "roami chrome record stop", "", nil},
	"chrome record status":               {"查看录制状态", "", "roami chrome record status", "", nil},
	"chrome operation-status":            {"查看持久化动作回执", "--operation-id ID --receipt-root PATH", "roami chrome operation-status --operation-id OPERATION_ID --receipt-root /tmp/receipts", "", nil},
	"chrome operation-cancel":            {"取消指定浏览器动作", "--operation-id ID --receipt-root PATH", "roami chrome operation-cancel --operation-id OPERATION_ID --receipt-root /tmp/receipts", "", nil},
	"plugin ls":                          {"列出插件", "[--json] [--removed]", "roami plugin ls [--json] [--removed]", "", nil},
	"plugin install":                     {"安装外部插件", "PATH|PACKAGE.tgz", "roami plugin install PATH|PACKAGE.tgz", "", nil},
	"plugin uninstall":                   {"卸载插件", "PLUGIN_ID [--purge]", "roami plugin uninstall PLUGIN_ID [--purge]", "", []string{"--purge 同时删除配置与数据；内置插件默认可恢复。"}},
	"plugin restore":                     {"恢复内置插件", "PLUGIN_ID", "roami plugin restore PLUGIN_ID", "", nil},
	"plugin info":                        {"查看插件详情", "PLUGIN_ID [--json]", "roami plugin info PLUGIN_ID [--json]", "", nil},
	"plugin enable":                      {"启用插件", "PLUGIN_ID", "roami plugin enable PLUGIN_ID", "", nil},
	"plugin disable":                     {"停用插件", "PLUGIN_ID", "roami plugin disable PLUGIN_ID", "", nil},
	"plugin run":                         {"调用插件命令", "PLUGIN.COMMAND [--key value ...]", "roami plugin run PLUGIN.COMMAND [--key value ...]", "", nil},
	"plugin findings":                    {"查看互审结果", "[--json]", "roami plugin findings [--json]", "", nil},
	"plugin notifications":               {"查看通知", "[--json]", "roami plugin notifications [--json]", "", nil},
	"plugin audit":                       {"查看审计日志", "[PLUGIN_ID] [--json]", "roami plugin audit [PLUGIN_ID] [--json]", "", nil},
	"plugin status":                      {"查看插件守护进程状态", "", "roami plugin status ", "", nil},
	"plugin track":                       {"登记会话供插件跟踪", "SESSION [--label KEY=VALUE ...]", "roami plugin track SESSION [--label KEY=VALUE ...]", "", nil},
	"plugin daemon":                      {"启动插件守护进程", "[--foreground]", "roami plugin daemon [--foreground]", "", nil},
}

func guidePage(name string) clihelp.Page {
	g := commandGuides[name]
	p := clihelp.Page{Command: "roami " + name, Summary: g.summary, Usage: []string{strings.TrimSpace("roami " + name + " " + g.syntax)}, Notes: g.notes}
	if g.example != "" {
		p.Examples = []clihelp.Entry{{Name: g.example}}
	}
	p.More = "roami --help"
	if index := strings.LastIndex(name, " "); index >= 0 {
		p.More = "roami " + name[:index] + " --help"
	}
	return p
}

// Flag descriptions and defaults come from the parser that executes the command.
type commandFlags struct {
	*flag.FlagSet
	page           func() clihelp.Page
	usageRequested bool
}

// Resolve the output stream after parsing, so errors keep stdout clean.
func (fs *commandFlags) Parse(args []string) error {
	fs.usageRequested = false
	err := fs.FlagSet.Parse(args)
	if fs.usageRequested {
		output := os.Stderr
		if err == flag.ErrHelp {
			output = os.Stdout
		}
		_ = fs.page().Render(output)
	}
	return err
}

func newCommandFlags(name string) *commandFlags {
	fs := &commandFlags{FlagSet: flag.NewFlagSet(name, flag.ContinueOnError)}
	fs.Usage = func() { fs.usageRequested = true }
	fs.page = func() clihelp.Page {
		p := guidePage(name)
		if p.Summary == "" {
			p.Summary = "命令参数"
			p.Usage = []string{"roami " + name + " [参数]"}
		}
		var rows []clihelp.Entry
		guide, indexed := commandGuides[name]
		allowed := strings.Fields(guide.options)
		fs.VisitAll(func(f *flag.Flag) {
			if indexed && !slices.Contains(allowed, f.Name) {
				return
			}
			valueName, description := flag.UnquoteUsage(f)
			label := "--" + f.Name
			if valueName != "" {
				label += " " + strings.ToUpper(valueName)
			}
			if f.DefValue != "" && f.DefValue != "false" && f.DefValue != "0" {
				description += fmt.Sprintf("（默认 %s）", f.DefValue)
			}
			rows = append(rows, clihelp.Entry{Name: label, Description: description})
		})
		p.Sections = []clihelp.Section{{Title: "参数", Entries: rows}}
		return p
	}
	return fs
}
