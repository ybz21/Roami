package swarm

import (
	"fmt"
	"io"
)

func HelpRequested(args []string) bool {
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
func showHelp(w io.Writer, topics []string) error {
	text := `roami swarm — Roami Main 蜂群协作

  new <名称> --key KEY --goal TEXT [--main-conversation ID] [--dir DIR]
  ls [--archived] [--json]
  status <群ID> [--follow] [--json]
  show <群ID> [--json]
  members <群ID> [--json]
  board <群ID> [--follow] [--json]
  work <群ID> <成员名或工作项ID> [--json]
  collect <群ID> [--json]
  chat <群ID> [--limit 50] [--follow] [--json]
  say <群ID> "消息" --key KEY [--to 成员 --task-revision N] [--json]
  member add <群ID> <成员名> --executor codex|claude|roami|opencode|pi
    --goal TEXT --acceptance TEXT --key KEY --revision N
    [--title TEXT] [--depends-on 成员@修订#产物ID]... [--integration]
  member ls <群ID> [--json]
  member show <群ID> <成员名或工作项ID> [--json]
  dependencies <群ID> <成员名或工作项ID> --key KEY --revision N
    [--depends-on 成员@修订#产物ID]... | --clear
  pause|resume|stop|archive <群ID> --key KEY --revision N [--json]
  plan|dependencies|control|say|post <群ID> --file request.json [--json]
  post <群ID> "讨论" --key KEY --task TASK --run RUN --task-revision N
  verify --input JSON（仅绑定本群 Main 的 Agent 工具上下文）
    必填 swarmId/taskId/revision/runId/accepted/checks/artifactIds
    先完整读取本轮文本产物；外部动作由用户界面/宿主核验，不能代填回执。
  help [命令] / <命令> --help

群ID、工作项、task、run 是不同身份；status 显示计划修订，members 显示任务修订。
new 默认复用节点 Main；成员由受管任务执行。结果经独立验收，不能手动移到完成。
指定成员的 say 会继续原任务；重试保持原 --key、文本、接收人和任务修订。
暂停只停新派发，停止调用任务取消，归档不关闭会话。修复依赖前先确认停止。
--json 为结构化输出；--follow 持续读取 SSE，断线退避重连，Ctrl-C 退出。
chat 是最近讨论与结果的快照；--follow 不保证补齐超出服务快照窗口的历史。
--file 包含完整请求；--file - 从 stdin 读 JSON。不与业务选项混用。
roami session swarm 访问同一实现。三维动画在 Web 的「协作」Tab 查看。
`
	_, err := fmt.Fprint(w, text)
	if err != nil {
		return err
	}
	if len(topics) > 0 {
		switch topics[0] {
		case "plan", "member":
			_, err = fmt.Fprint(w, `
plan.json 示例（--revision 为计划修订）：
{"commandKey":"plan-1","expectedRevision":1,"items":[{"member":"api","executor":"codex","title":"接口实现","goal":"实现接口","acceptance":"接口测试通过"},{"member":"check","executor":"native","title":"集成验收","goal":"检查上游交付","acceptance":"端到端验证通过","integration":true}]}
`)
		case "say", "post", "chat", "feed":
			_, err = fmt.Fprint(w, `
给 Main：roami swarm say <群ID> "补充需求" --key note-1
继续成员任务：roami swarm say <群ID> "补充测试" --to api --task-revision 1 --key revise-1
实时群聊：roami swarm chat <群ID> --follow
成员回传文件：{"commandKey":"report-note-1","text":"接口已就绪，待验收","taskId":"TASK","runId":"RUN","taskRevision":1}
`)
		case "pause", "resume", "stop", "archive", "control":
			_, err = fmt.Fprint(w, `
roami swarm pause <群ID> --key pause-1 --revision 2
control.json：{"commandKey":"pause-1","expectedRevision":2,"action":"pause"}
`)
		case "dependencies":
			_, err = fmt.Fprint(w, `
roami swarm dependencies <群ID> check --depends-on api@2 --key deps-2 --revision 3
产物绑定：--depends-on 'api@2#ARTIFACT_ID'；批量依赖可用 --file。
`)
		}
	}
	return err
}
