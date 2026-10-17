// feishu.go 是飞书 provider(自建应用):长连接订阅 im.message.receive_v1
// 归一化成 Message,发送走应用 API(消息/交互卡片)。
//
// 接入要点:开放平台建「企业自建应用」→ 开通 im:message 收发权限 → 事件订阅
// 选「使用长连接接收事件」并订阅「接收消息」→ 发布版本 → 应用机器人拉进群。
package im

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"regexp"
	"time"

	lark "github.com/larksuite/oapi-sdk-go/v3"
	larkcore "github.com/larksuite/oapi-sdk-go/v3/core"
	"github.com/larksuite/oapi-sdk-go/v3/event/dispatcher"
	larkim "github.com/larksuite/oapi-sdk-go/v3/service/im/v1"
	larkws "github.com/larksuite/oapi-sdk-go/v3/ws"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

type feishuProvider struct{}

func (feishuProvider) Name() string { return "feishu" }

var mentionKeyRe = regexp.MustCompile(`@_user_\d+`)

func (feishuProvider) Listen(ctx *sdk.Ctx, onMsg func(Message)) error {
	appID, appSecret := ctx.Config["app_id"], ctx.Config["app_secret"]
	if appID == "" || appSecret == "" {
		return fmt.Errorf("app_id/app_secret 未配置(飞书开放平台建自建应用后: roami plugin config im-bridge set app_id <cli_xxx> && set app_secret <secret>)")
	}
	handler := dispatcher.NewEventDispatcher("", "").
		OnP2MessageReceiveV1(func(_ context.Context, ev *larkim.P2MessageReceiveV1) error {
			// RPC 连接支持并发调用;回调里不做重活,避免阻塞 ws 心跳
			go onMsg(feishuToMessage(ev))
			return nil
		})
	cli := larkws.NewClient(appID, appSecret,
		larkws.WithEventHandler(handler),
		// SDK 默认 logger 写 stdout,而插件进程的 stdout 是 JSON-RPC 通道,
		// 必须改道 stderr(进面板/日志),否则污染协议流且排障全盲
		larkws.WithLogger(stderrLogger{}),
		larkws.WithLogLevel(larkcore.LogLevelInfo))
	if err := cli.Start(context.Background()); err != nil {
		return fmt.Errorf("检查 app 凭据与「事件订阅-长连接」开关: %w", err)
	}
	return nil
}

// feishuToMessage 归一化飞书事件(@占位符剥除、字段拍平)。
func feishuToMessage(ev *larkim.P2MessageReceiveV1) Message {
	msg := ev.Event.Message
	if msg == nil {
		return Message{}
	}
	m := Message{
		ID:        strVal(msg.MessageId),
		Chat:      strVal(msg.ChatId),
		ChatType:  strVal(msg.ChatType),
		Kind:      strVal(msg.MessageType),
		Mentioned: len(msg.Mentions) > 0,
	}
	if ev.Event.Sender != nil && ev.Event.Sender.SenderId != nil {
		m.Sender = strVal(ev.Event.Sender.SenderId.OpenId)
	}
	var content struct {
		Text string `json:"text"`
	}
	_ = json.Unmarshal([]byte(strVal(msg.Content)), &content)
	m.Text = mentionKeyRe.ReplaceAllString(content.Text, "")
	return m
}

func (feishuProvider) SendText(ctx *sdk.Ctx, chatID, text string) error {
	content, _ := json.Marshal(map[string]string{"text": text})
	return feishuSend(ctx, chatID, "text", string(content))
}

func (feishuProvider) SendCard(ctx *sdk.Ctx, chatID string, c card) error {
	content, err := json.Marshal(feishuCardContent(c))
	if err != nil {
		return err
	}
	return feishuSend(ctx, chatID, "interactive", string(content))
}

func feishuSend(ctx *sdk.Ctx, chatID, msgType, content string) error {
	appID, appSecret := ctx.Config["app_id"], ctx.Config["app_secret"]
	if appID == "" || appSecret == "" {
		return fmt.Errorf("app_id/app_secret not configured")
	}
	client := lark.NewClient(appID, appSecret, lark.WithLogger(stderrLogger{}))
	req := larkim.NewCreateMessageReqBuilder().
		ReceiveIdType("chat_id").
		Body(larkim.NewCreateMessageReqBodyBuilder().
			ReceiveId(chatID).MsgType(msgType).Content(content).Build()).
		Build()
	cctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	resp, err := client.Im.Message.Create(cctx, req)
	if err != nil {
		return fmt.Errorf("feishu send failed: %w", err)
	}
	if !resp.Success() {
		return fmt.Errorf("feishu send rejected: code=%d msg=%s", resp.Code, resp.Msg)
	}
	ctx.Logf("feishu message sent: chat=%s type=%s", chatID, msgType)
	return nil
}

// feishuCardContent renders the lark interactive-card JSON.
func feishuCardContent(c card) map[string]any {
	template := map[string]string{"high": "red", "warning": "orange", "info": "blue"}[c.Severity]
	if template == "" {
		template = "blue"
	}
	body := c.Body
	if body == "" {
		body = "(无正文)"
	}
	return map[string]any{
		"header": map[string]any{
			"title":    map[string]any{"tag": "plain_text", "content": c.Title},
			"template": template,
		},
		"elements": []any{
			map[string]any{"tag": "markdown", "content": body},
			map[string]any{"tag": "note", "elements": []any{
				map[string]any{"tag": "plain_text", "content": "Roami · " + c.Source},
			}},
		},
	}
}

// stderrLogger routes lark SDK logs to stderr(stdout 被 RPC 占用)。
type stderrLogger struct{}

func (stderrLogger) Debug(_ context.Context, a ...interface{}) { logLine("DEBUG", a...) }
func (stderrLogger) Info(_ context.Context, a ...interface{})  { logLine("INFO", a...) }
func (stderrLogger) Warn(_ context.Context, a ...interface{})  { logLine("WARN", a...) }
func (stderrLogger) Error(_ context.Context, a ...interface{}) { logLine("ERROR", a...) }

func logLine(level string, a ...interface{}) {
	fmt.Fprintf(os.Stderr, "[lark %s] %s\n", level, fmt.Sprint(a...))
}

func strVal(p *string) string {
	if p == nil {
		return ""
	}
	return *p
}
