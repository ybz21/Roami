// listen.go 是 IM 桥的通用入站核心:向当前 provider(飞书/钉钉…)要一条
// 归一化消息流,做去重与 @过滤,然后交给 concierge(默认)或 legacy 模式。
// 具体 IM 的长连接协议、消息格式全部隔离在各自的 provider 文件里。
package im

import (
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

// listen 命令:前台长连接监听(plugind 托管在 _ttmux-im 会话里,掉线/回收后
// 自动重拉;手动跑 `roami plugin run im-bridge.listen` 也可以,面板即界面)。
func listen(ctx *sdk.Ctx, args map[string]string) (any, error) {
	prov, err := activeProvider(ctx)
	if err != nil {
		return nil, err
	}
	fmt.Fprintf(os.Stderr, "== im-bridge 长连接监听(provider: %s)==\n@机器人 说「帮助」看用法;消息将进常驻管家(concierge)处理\n", prov.Name())

	st := &conciergeState{}
	if conciergeMode(ctx) {
		if err := ensureWorkspace(ctx); err != nil {
			return nil, fmt.Errorf("workspace init failed: %w", err)
		}
		runConciergeLoops(ctx, st)
		fmt.Fprintf(os.Stderr, "管家工作目录: %s(AGENT.md 可自定义)\n", workspaceDir(ctx))
	}

	seen := &seenSet{ids: map[string]struct{}{}}
	if err := prov.Listen(ctx, func(m Message) {
		handleMessage(ctx, st, seen, m)
	}); err != nil {
		return nil, fmt.Errorf("%s 长连接失败: %w", prov.Name(), err)
	}
	return map[string]string{"stopped": "listener closed"}, nil
}

// seenSet 是消息级去重(IM 事件可能重投)。
type seenSet struct {
	mu  sync.Mutex
	ids map[string]struct{}
}

func (s *seenSet) firstTime(id string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.ids[id]; ok {
		return false
	}
	if len(s.ids) > 1024 { // 简单封顶,长连接进程日级回收,无需 LRU
		s.ids = map[string]struct{}{}
	}
	s.ids[id] = struct{}{}
	return true
}

// conciergeMode reports whether task_mode selects the resident concierge(默认)。
func conciergeMode(ctx *sdk.Ctx) bool {
	m := strings.TrimSpace(ctx.Config["task_mode"])
	return m == "" || m == "concierge"
}

// handleMessage 处理一条归一化的入站消息(provider 无关)。
func handleMessage(ctx *sdk.Ctx, st *conciergeState, seen *seenSet, m Message) {
	if m.Chat == "" {
		return
	}
	if m.ID != "" && !seen.firstTime(m.ID) {
		return
	}
	// 先记日志再过滤:排障时能看到"收到了但被谁拦下"
	ctx.Logf("im inbound: chat=%s sender=%s type=%s kind=%s mentioned=%v",
		m.Chat, m.Sender, m.ChatType, m.Kind, m.Mentioned)
	// 群聊只响应 @机器人;单聊全收
	if m.ChatType != "p2p" && !m.Mentioned {
		return
	}
	if m.Kind != "text" {
		replyText(ctx, m.Chat, "目前只认识文字消息;@我 说「帮助」看用法。")
		return
	}
	text := strings.TrimSpace(m.Text)
	ctx.Logf("im inbound text (%s): %s", m.Chat, text)

	if conciergeMode(ctx) {
		handleConciergeMessage(ctx, st, m.Chat, m.Sender, text)
		return
	}

	switch strings.ToLower(text) {
	case "", "hi", "hello", "你好", "help", "帮助", "?", "？":
		replyText(ctx, m.Chat, "我是 Roami 机器人,@我 之后:\n"+
			"· 帮助 —— 看这份说明\n"+
			"· 状态 —— 看我派出去的任务会话\n"+
			"· 绑定通知 —— Roami 系统通知(互审结果、告警)以后发到本群\n"+
			"· 结束 —— 收掉当前任务会话\n"+
			"· 其他任何话 —— 派给 Agent 干活;它会主动汇报进度、有疑问会反问你,你的回复我会转给它")
	case "状态", "status":
		replyText(ctx, m.Chat, statusText(ctx))
	case "绑定通知", "bind":
		if err := ctx.StorageSet("notify_chat", m.Chat); err != nil {
			replyText(ctx, m.Chat, "绑定失败: "+err.Error())
			return
		}
		replyText(ctx, m.Chat, "已绑定 ✅ Roami 系统通知(互审结果、blocking finding、告警)以后发到本群;「解绑通知」可取消。")
	case "解绑通知", "unbind":
		_ = ctx.StorageSet("notify_chat", "")
		replyText(ctx, m.Chat, "已解绑,Roami 系统通知不再发送(重新绑定:任意群里说「绑定通知」)。")
	case "结束", "stop", "exit":
		if sess := activeTask(ctx, m.Chat); sess != "" {
			_ = ctx.SessionSend(sess, "/exit")
			replyText(ctx, m.Chat, "已请求结束会话 "+sess+"。")
		} else {
			replyText(ctx, m.Chat, "当前没有进行中的任务会话。")
		}
	default:
		// 有进行中的任务会话:你的话是给它的(追问/答复/新指示),直接转进去
		if sess := activeTask(ctx, m.Chat); sess != "" {
			if err := ctx.SessionSend(sess, text); err != nil {
				replyText(ctx, m.Chat, "转达失败: "+err.Error())
				return
			}
			ctx.Logf("im forwarded to %s: %s", sess, text)
			return
		}
		dispatchTask(ctx, m.Chat, text)
	}
}

// activeTask 返回该 IM 会话当前存活的任务会话(最近优先)。
func activeTask(ctx *sdk.Ctx, chatID string) string {
	rows, err := ctx.SessionList()
	if err != nil {
		return ""
	}
	for i := len(rows) - 1; i >= 0; i-- {
		r := rows[i]
		if r.Labels["im:chat"] == chatID && r.Labels["role"] == "im-task" && ctx.SessionAlive(r.Session) {
			return r.Session
		}
	}
	return ""
}

// dispatchTask 拉一个交互式 Agent 会话干活:对话主导权在 Agent——prompt 注入
// 「im-bridge.send」用法,由它自己决定何时汇报、提问、收尾;用户的后续
// 消息经 handleMessage 路由回该会话(task_mode=oneshot 退回老的一次性模式)。
func dispatchTask(ctx *sdk.Ctx, chatID, text string) {
	workdir := ctx.Config["workdir"]
	if workdir == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			replyText(ctx, chatID, "派活失败:未配置 workdir 且拿不到家目录")
			return
		}
		workdir = home
	}
	sess := "im-" + time.Now().Format("0102-150405")
	interactive := ctx.Config["task_mode"] != "oneshot"
	var prompt string
	if interactive {
		prompt = fmt.Sprintf(`你在为一位 IM 用户干活。与 TA 沟通的唯一渠道是执行这条命令(用 Bash):
  roami plugin run im-bridge.send --chat %s --text '要发的内容'
沟通规则:
- 开工时先发一条简短消息说明你的理解和计划;
- 缺信息或需要用户拍板时,发消息提问后停下等待,用户的回复会作为新消息直接出现在本对话里;
- 干活过程中关键节点可发简短进度;
- 完成后必须发一条最终总结(做了什么、结果、涉及路径),控制在几百字内;
- 发完最终总结后执行 Bash 命令 tmux kill-session -t %s 结束本会话(这就是"交活"信号)。
用户的任务:
%s`, chatID, sess, text)
	} else {
		prompt = text + "\n\n(此任务来自 IM @机器人 派活;完成后请输出一段简明的结果总结,便于转发回群。)"
	}
	name, err := ctx.AgentSpawn(sdk.SpawnReq{
		Provider:    ctx.Config["provider"],
		Prompt:      prompt,
		SessionName: sess,
		Workdir:     workdir,
		Interactive: interactive,
		Labels: map[string]string{"im:chat": chatID, "role": "im-task",
			"im:mode": map[bool]string{true: "interactive", false: "oneshot"}[interactive]},
	})
	if err != nil {
		ctx.Logf("im task spawn failed: %v", err)
		replyText(ctx, chatID, "派活失败: "+err.Error())
		return
	}
	ctx.Logf("im task spawned: session=%s workdir=%s interactive=%v", name, workdir, interactive)
	if !interactive {
		replyText(ctx, chatID, fmt.Sprintf("已开工 🛠️\n会话: %s\n目录: %s\n围观: roami session a %s\n完成后我会在这里回报结果。", name, workdir, name))
	}
	// 交互模式不由插件发「已开工」——Agent 自己会先打招呼说明计划
}

func statusText(ctx *sdk.Ctx) string {
	rows, err := ctx.SessionList()
	if err != nil {
		return "查询失败: " + err.Error()
	}
	var b strings.Builder
	n := 0
	for i := len(rows) - 1; i >= 0 && n < 8; i-- {
		r := rows[i]
		if r.Labels["role"] != "im-task" {
			continue
		}
		fmt.Fprintf(&b, "· %s [%s]\n", r.Session, r.Status)
		n++
	}
	if n == 0 {
		return "还没有派过任务;@我 直接说要干什么即可。"
	}
	return "最近的任务会话:\n" + strings.TrimRight(b.String(), "\n")
}

// send 命令:供派活 Agent 在任务里主动给用户发消息(进度、提问、总结)。
// `roami plugin run im-bridge.send --chat <chat_id> --text '...'`
func send(ctx *sdk.Ctx, args map[string]string) (any, error) {
	chat, text := args["chat"], args["text"]
	if chat == "" {
		chat = notifyChat(ctx) // 不指定就发到绑定的通知群
	}
	if chat == "" || text == "" {
		return nil, fmt.Errorf("usage: roami plugin run im-bridge.send --chat <chat_id> --text <文本>(chat 可省略,默认绑定的通知群)")
	}
	prov, err := activeProvider(ctx)
	if err != nil {
		return nil, err
	}
	if err := prov.SendText(ctx, chat, text); err != nil {
		return nil, err
	}
	return map[string]string{"sent": "ok", "chat": chat, "provider": prov.Name()}, nil
}
