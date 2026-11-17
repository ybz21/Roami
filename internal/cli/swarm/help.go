package swarm

import (
	"fmt"
	agentcommands "github.com/ybz21/Roami/agent-runtime"
	"io"
	"slices"
	"strings"

	"github.com/ybz21/Roami/internal/agent"
	clihelp "github.com/ybz21/Roami/internal/cli/help"
)

func HelpRequested(args []string) bool {
	if len(args) > 1 && args[len(args)-1] == "help" && NativeHelpTopic(args[:len(args)-1]) {
		return true
	}
	if len(args) > 0 && args[0] == "help" {
		return true
	}
	for _, arg := range args {
		if arg == "--" {
			break
		}
		if arg == "--help" || arg == "-h" {
			return true
		}
	}
	return false
}

type helpSpec struct {
	summary, syntax, example string
	notes                    []string
}

var helpSpecs = map[string]helpSpec{
	"new":             {"创建蜂群", "NAME --key KEY --goal TEXT [--main-conversation ID] [--dir PATH]", `roami swarm new review --key review-1 --goal "检查项目"`, []string{"默认复用节点 Main；成员由受管任务执行。"}},
	"ls":              {"列出蜂群", "[--archived] [--json]", "roami swarm ls --json", nil},
	"status":          {"查看蜂群状态与计划修订", "SWARM_ID [--follow] [--json]", "roami swarm status SWARM_ID --follow", nil},
	"show":            {"查看蜂群详情", "SWARM_ID [--json]", "roami swarm show SWARM_ID --json", nil},
	"members":         {"查看成员与任务修订", "SWARM_ID [--json]", "roami swarm members SWARM_ID --json", nil},
	"board":           {"查看看板", "SWARM_ID [--follow] [--json]", "roami swarm board SWARM_ID --follow", []string{"结果经独立验收，不能手动移到完成。"}},
	"work":            {"查看成员或工作项", "SWARM_ID MEMBER|WORK_ID [--json]", "roami swarm work SWARM_ID api --json", nil},
	"collect":         {"收集成员结果", "SWARM_ID [--json]", "roami swarm collect SWARM_ID --json", nil},
	"chat":            {"查看最近讨论与结果", "SWARM_ID [--limit N] [--follow] [--json]", "roami swarm chat SWARM_ID --follow", []string{"--follow 不保证补齐超出快照窗口的历史。"}},
	"inbox":           {"查看待处理消息", "SWARM_ID [--member ID] [--before N] [--limit N] [--json]\n  roami swarm inbox SWARM_ID --task ID --run ID --task-revision N [--json]", "roami swarm inbox SWARM_ID --limit 20", []string{"普通查看不冒充 Main 已读；绑定成员读取只记录获取，不表示已解决或任务完成。"}},
	"daily":           {"从外部日程唤醒持续目标", "SWARM_ID --delegation ID --project ID --main-conversation ID --timezone IANA --date YYYY-MM-DD --slot NAME [--dry-run] [--json]", "roami swarm daily SWARM_ID --delegation DELEGATION_ID --project PROJECT_ID --main-conversation CONVERSATION_ID --timezone Asia/Shanghai --date YYYY-MM-DD --slot morning --dry-run", []string{"先用 --dry-run 核对目标；同日本地时段去重，不发送新用户消息。", "不登记日程、不授权发布，accepted 只表示通知已保存。"}},
	"say":             {"给 Main 或成员补充需求", `SWARM_ID TEXT --key KEY [--to MEMBER --task-revision N] [--json]`, `roami swarm say SWARM_ID "补充测试" --to api --task-revision 1 --key revise-1`, []string{"指定成员时继续原任务；未知结果保持原 key、文本、接收人与任务修订。"}},
	"post":            {"回传成员讨论与进展", "SWARM_ID TEXT --key KEY --task ID --run ID --task-revision N [选项]", `roami swarm post SWARM_ID "接口已就绪，待验收" --key note-1 --task TASK_ID --run RUN_ID --task-revision 1`, []string{"可选 --kind progress|question|blocker|handoff|reply、--message-key KEY、--reply-to ID、--recipient-member ID。", "question / blocker / handoff 持久等待原 Main 处理；不会自动唤醒模型或注入终端。"}},
	"plan":            {"更新蜂群计划", "SWARM_ID --file JSON|- [--json]", "roami swarm plan SWARM_ID --file plan.json", []string{`JSON 示例：{"commandKey":"plan-1","expectedRevision":1,"items":[{"member":"api","executor":"codex","title":"接口实现","goal":"实现接口","acceptance":"接口测试通过"}]}`, "计划使用 expectedRevision；结果需独立验收。"}},
	"member add":      {"派发成员任务", "SWARM_ID NAME --executor EXECUTOR --goal TEXT --acceptance TEXT --key KEY --revision N [选项]", `roami swarm member add SWARM_ID api --executor codex --goal "实现接口" --acceptance "测试通过" --key api-1 --revision 1`, []string{"可选 --member-id ID、--title TEXT、--depends-on '成员@修订#产物ID'、--integration。", "登记后的成员必须传 --member-id，不按新名字创建替代成员。"}},
	"member register": {"登记成员职责", "SWARM_ID NAME --executor EXECUTOR --duty TEXT --key KEY --revision N", `roami swarm member register SWARM_ID api --executor codex --duty "接口开发" --key api-role-1 --revision 1`, []string{"只登记职责，不派发任务、不创建运行实例；后续计划须传 memberId。"}},
	"member inspect":  {"查看成员执行轮次", "SWARM_ID MEMBER_ID [--before N] [--limit N] [--json]", "roami swarm member inspect SWARM_ID MEMBER_ID --limit 20", nil},
	"member ls":       {"列出成员", "SWARM_ID [--json]", "roami swarm member ls SWARM_ID --json", nil},
	"member show":     {"查看成员工作项", "SWARM_ID MEMBER|WORK_ID [--json]", "roami swarm member show SWARM_ID api --json", nil},
	"dependencies":    {"更新工作项依赖", "SWARM_ID MEMBER|WORK_ID --key KEY --revision N [--depends-on SPEC ... | --clear]", "roami swarm dependencies SWARM_ID check --depends-on 'api@2#ARTIFACT_ID' --key deps-2 --revision 3", []string{"修复依赖前先确认停止；批量依赖可用 --file JSON。"}},
	"control":         {"批量控制蜂群", "SWARM_ID --file JSON|- [--json]", "roami swarm control SWARM_ID --file control.json", []string{`JSON 示例：{"commandKey":"pause-1","expectedRevision":2,"action":"pause"}`}},
}

func showHelp(w io.Writer, topics []string) error {
	name := strings.Join(topics, " ")
	aliases := map[string]string{"create": "new", "list": "ls", "feed": "chat", "member-add": "member add", "member-register": "member register", "member-inspect": "member inspect", "member list": "member ls"}
	if alias, ok := aliases[name]; ok {
		name = alias
	}
	specs := make(map[string]helpSpec, len(helpSpecs)+4)
	for k, v := range helpSpecs {
		specs[k] = v
	}
	for command, summary := range map[string]string{"pause": "暂停新派发", "resume": "继续派发", "stop": "取消蜂群任务", "archive": "归档蜂群"} {
		specs[command] = helpSpec{summary, "SWARM_ID --key KEY --revision N [--json]", "roami swarm " + command + " SWARM_ID --key " + command + "-1 --revision 2", []string{"暂停只停新派发，停止调用任务取消，归档不关闭会话。"}}
	}
	p := clihelp.Page{Command: "roami swarm", Summary: "蜂群协作、群聊与看板", Usage: []string{"roami swarm <命令> [参数]"}, More: "roami swarm <命令> -h"}
	if spec, ok := specs[name]; ok {
		p.Command += " " + name
		p.Summary = spec.summary
		p.Usage = []string{p.Command + " " + spec.syntax}
		p.Examples = []clihelp.Entry{{Name: spec.example}}
		p.Notes = spec.notes
		p.Sections = []clihelp.Section{{Title: "通用选项", Entries: []clihelp.Entry{{Name: "--json", Description: "输出 JSON"}}}}
		if slices.Contains([]string{"plan", "control", "member add", "member register", "dependencies", "say", "post"}, name) {
			p.Sections[0].Entries = append(p.Sections[0].Entries, clihelp.Entry{Name: "--file JSON|-", Description: "读取完整请求；- 表示标准输入，不与业务选项混用"})
		}
		p.More = "roami swarm --help"
	} else {
		if name != "" && name != "member" {
			return fmt.Errorf("未知蜂群帮助主题 %q；使用 roami swarm --help 查看命令", name)
		}
		var rows []clihelp.Entry
		for command, spec := range specs {
			if name == "member" && strings.HasPrefix(command, "member ") {
				rows = append(rows, clihelp.Entry{Name: strings.TrimPrefix(command, "member "), Description: spec.summary})
			} else if name != "member" && !strings.Contains(command, " ") {
				rows = append(rows, clihelp.Entry{Name: command, Description: spec.summary})
			}
		}
		if name == "member" {
			p.Command += " member"
			p.Summary = "登记、派发与查看成员"
			p.Usage = []string{"roami swarm member <命令> [参数]"}
			p.More = "roami swarm member <命令> -h"
		} else {
			rows = append(rows, clihelp.Entry{Name: "member", Description: "登记、派发与查看成员"})
		}
		if name == "" {
			seen := map[string]bool{}
			for _, row := range rows {
				seen[row.Name] = true
			}
			for _, path := range agentcommands.Paths() {
				if len(path) > 1 && path[0] == "swarm" && !NativeHelpTopic(path[1:]) && !seen[path[1]] {
					rows = append(rows, clihelp.Entry{Name: path[1], Description: "使用当前 Agent 上下文的已注册能力"})
					seen[path[1]] = true
				}
			}
		}
		slices.SortFunc(rows, func(a, b clihelp.Entry) int { return strings.Compare(a.Name, b.Name) })
		p.Sections = []clihelp.Section{{Title: "命令", Entries: rows}}
		p.Examples = []clihelp.Entry{{Name: "roami swarm ls"}, {Name: "roami swarm status SWARM_ID --follow"}, {Name: "roami swarm member add -h"}}
	}
	if name == "" || strings.Contains(specs[name].syntax, "--follow") {
		p.Notes = append(p.Notes, "--follow 持续读取，断线退避重连；Ctrl-C 退出。")
	}
	p.Notes = append(p.Notes, "群 ID、成员 ID、task、run 与修订是不同身份；使用状态查询返回的值。", "执行器："+strings.Join(append([]string{"native"}, agent.Kinds()...), ", ")+"；roami 是 native 的别名。")
	return p.Render(w)
}

func NativeHelpTopic(topics []string) bool {
	name := strings.Join(topics, " ")
	if _, ok := helpSpecs[name]; ok {
		return true
	}
	return slices.Contains([]string{"", "member", "create", "list", "feed", "member-add", "member-register", "member-inspect", "member list", "pause", "resume", "stop", "archive"}, name)
}
