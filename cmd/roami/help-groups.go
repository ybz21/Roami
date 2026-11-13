package main

import (
	"fmt"
	agentcommands "github.com/ybz21/Roami/agent-runtime"
	"os"
	"slices"
	"strings"

	clihelp "github.com/ybz21/Roami/internal/cli/help"
)

var helpGroups = map[string]string{
	"":        "会话、项目与智能体的统一命令入口",
	"project": "管理项目目录与项目信息", "project okr": "管理项目目标、记录与复盘",
	"auth": "管理服务登录", "db": "查看、迁移与备份数据库",
	"agent": "管理智能体、对话与任务", "agent capability": "发现与调用已安装能力",
	"agent capability market": "搜索、预览与安装能力", "agent reminder": "管理提醒",
	"agent notification-preferences": "管理通知偏好", "agent control": "管理任务资源输入",
	"agent execution": "查看与管理执行器任务", "agent gateway": "管理模型网关配置与用量",
	"agent mcp": "管理独立 MCP 服务", "speech": "使用节点语音服务",
	"chrome": "操作浏览器标签页与页面", "chrome record": "录制浏览器画面",
	"plugin": "管理插件",
}

func groupHelpPage(name string) clihelp.Page {
	command := strings.TrimSpace("roami " + name)
	p := clihelp.Page{Command: command, Summary: helpGroups[name], Usage: []string{command + " <命令> [参数]", command + " <命令> -h"}, More: command + " <命令> --help"}
	prefix := ""
	if name != "" {
		prefix = name + " "
	}
	var rows []clihelp.Entry
	for path, guide := range commandGuides {
		if rest, ok := strings.CutPrefix(path, prefix); ok && !strings.Contains(rest, " ") {
			rows = append(rows, clihelp.Entry{Name: rest, Description: guide.summary})
		}
	}
	for path, summary := range helpGroups {
		if rest, ok := strings.CutPrefix(path, prefix); ok && rest != "" && !strings.Contains(rest, " ") {
			rows = append(rows, clihelp.Entry{Name: rest, Description: summary})
		}
	}
	if name == "" {
		rows = append(rows, clihelp.Entry{Name: "session", Description: "管理会话、终端与环境"}, clihelp.Entry{Name: "swarm", Description: "蜂群协作、群聊与看板"}, clihelp.Entry{Name: "adb", Description: "Android 设备操作（透传系统 ADB）"}, clihelp.Entry{Name: "server", Description: "启动 Web 服务"}, clihelp.Entry{Name: "help", Description: "查看命令帮助"})
		p.Command += " " + displayVersion()
		p.Sections = append(p.Sections, clihelp.Section{Title: "全局路径选项（放在命令之前）", Entries: []clihelp.Entry{{Name: "--home PATH", Description: "实例目录"}, {Name: "--data-dir PATH", Description: "数据目录"}, {Name: "--database-dir PATH", Description: "数据库目录"}, {Name: "--backup-dir PATH", Description: "备份目录"}, {Name: "--config PATH", Description: "配置文件"}}})
		p.Examples = []clihelp.Entry{{Name: "roami project ls"}, {Name: "roami session ls --tree"}, {Name: "roami session fork -h"}}
	} else {
		for _, example := range []string{"project ls", "auth login", "db status", "agent status", "agent capability list", "agent reminder ls", "agent notification-preferences get", "agent control ls", "agent trace", "speech transcribe", "chrome tabs", "plugin ls"} {
			if strings.HasPrefix(example, prefix) && commandGuides[example].example != "" {
				p.Examples = []clihelp.Entry{{Name: commandGuides[example].example}}
				break
			}
		}
	}
	seen := map[string]bool{}
	for _, row := range rows {
		seen[row.Name] = true
	}
	for _, path := range agentcommands.Paths() {
		full := strings.Join(path, " ")
		rest, ok := strings.CutPrefix(full, prefix)
		if !ok || rest == "" {
			continue
		}
		child, _, _ := strings.Cut(rest, " ")
		if !seen[child] {
			rows = append(rows, clihelp.Entry{Name: child, Description: "使用 Agent 上下文的已注册能力"})
			seen[child] = true
		}
	}
	slices.SortFunc(rows, func(a, b clihelp.Entry) int { return strings.Compare(a.Name, b.Name) })
	if len(p.Examples) == 0 && len(rows) > 0 {
		p.Examples = []clihelp.Entry{{Name: command + " " + rows[0].Name + " -h", Description: "查看该命令的参数与示例"}}
	}

	p.Sections = append([]clihelp.Section{{Title: "命令", Entries: rows}}, p.Sections...)
	return p
}

// Help paths contain only command words, never positional values or flag payloads.
func showCLIHelp(args []string) (bool, int) {
	if len(args) == 0 {
		return false, 0
	}
	path := slices.Clone(args)
	requested := false
	if path[0] == "help" || path[0] == "commands" {
		path = path[1:]
		requested = true
	} else if clihelp.IsHelp(path[len(path)-1]) {
		path = path[:len(path)-1]
		requested = true
	}
	if len(path) > 1 && path[len(path)-2] == "help" {
		path = append(path[:len(path)-2], path[len(path)-1])
		requested = true
	}
	name := strings.Join(path, " ")
	if name == "chrome shot" {
		name = "chrome screenshot"
		path = []string{"chrome", "screenshot"}
	}
	if name == "plugin list" {
		name = "plugin ls"
		path = []string{"plugin", "ls"}
	}
	if name == "session" || strings.HasPrefix(name, "session ") || name == "swarm" || strings.HasPrefix(name, "swarm ") || name == "adb" || strings.HasPrefix(name, "adb ") {
		return false, 0
	}
	if _, ok := helpGroups[name]; ok && (requested || len(args) > 0 && name != "") {
		_ = groupHelpPage(name).Render(os.Stdout)
		return true, 0
	}
	if !requested {
		return false, 0
	}
	if name == "server" {
		printServerHelp()
		return true, 0
	}
	if _, ok := commandGuides[name]; !ok {
		for _, registered := range agentcommands.Paths() {
			if len(path) <= len(registered) && slices.Equal(path, registered[:len(path)]) {
				return false, 0
			}
		}
		if len(path) > 0 && helpGroups[path[0]] != "" {
			fmt.Fprintf(os.Stderr, "未知命令 %q；使用 roami %s --help 查看命令\n", name, path[0])
			return true, 2
		}
		return false, 0
	}
	code := 0
	switch path[0] {
	case "project", "auth":
		code = runAPICommand(path[0], append(path[1:], "--help"))
	case "agent":
		if slices.Contains([]string{"agent installed-status", "agent prepare-upgrade", "agent resume-upgrade"}, name) {
			_ = guidePage(name).Render(os.Stdout)
		} else {
			code = runAgent(append(path[1:], "--help"))
		}
	case "db":
		code = runDatabase(append(path[1:], "--help"))
	case "speech":
		code = runSpeech(append(path[1:], "--help"))
	default:
		_ = terminalCommandPage(name).Render(os.Stdout)
	}
	return true, code
}

func printServerHelp() {
	_ = (clihelp.Page{Command: "roami server", Summary: "启动 Web 服务", Usage: []string{"roami server [选项]"}, Sections: []clihelp.Section{{Title: "参数", Entries: []clihelp.Entry{
		{Name: "-config PATH", Description: "配置文件"}, {Name: "-addr HOST:PORT", Description: "监听地址"}, {Name: "-web PATH", Description: "前端构建目录"}, {Name: "-tls", Description: "启用 HTTPS"}, {Name: "-tls-cert PATH", Description: "TLS 证书"}, {Name: "-tls-key PATH", Description: "TLS 私钥"},
	}}}, Examples: []clihelp.Entry{{Name: "roami server -addr 127.0.0.1:13579"}}, More: "roami --help"}).Render(os.Stdout)
}
