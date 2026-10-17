// provider.go 定义 IM 提供方适配器:核心(管家/inbox/委派/白名单)与具体
// IM 无关,飞书/钉钉/企微等只需实现 Provider 三件事——收(长连接归一化回调)、
// 发文本、发卡片。新增一个 IM = 新增一个 provider 文件 + registry 一行。
package im

import (
	"fmt"
	"strings"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

// Message 是各 IM 归一化后的入站消息。
type Message struct {
	ID        string // 消息 id,核心用它去重
	Chat      string // 会话 id(回复定向用)
	Sender    string // 发送者 open_id / userid
	ChatType  string // p2p | group
	Kind      string // text | other
	Text      string
	Mentioned bool // 群聊中是否 @ 了机器人
}

// card 是跨 provider 的通知卡片(标题/级别/正文/来源脚注)。
type card struct {
	Title    string
	Severity string
	Body     string
	Source   string
}

// Provider 是一个 IM 的最小接入面。
type Provider interface {
	Name() string
	// Listen 建立长连接并阻塞运行,把归一化消息回调给 onMsg。
	Listen(ctx *sdk.Ctx, onMsg func(Message)) error
	// SendText / SendCard 向指定会话发消息。
	SendText(ctx *sdk.Ctx, chatID, text string) error
	SendCard(ctx *sdk.Ctx, chatID string, c card) error
}

// activeProvider 按配置解析当前 IM 提供方(默认 feishu)。
func activeProvider(ctx *sdk.Ctx) (Provider, error) {
	name := strings.TrimSpace(ctx.Config["im_provider"])
	switch name {
	case "", "feishu":
		return feishuProvider{}, nil
	case "dingtalk":
		return dingtalkProvider{}, nil
	}
	return nil, fmt.Errorf("unknown im_provider %q (supported: feishu, dingtalk)", name)
}

// replyText / replyCard 是核心代码的统一出口(provider 由配置解析)。
func replyText(ctx *sdk.Ctx, chatID, text string) {
	p, err := activeProvider(ctx)
	if err != nil {
		ctx.Logf("reply skipped: %v", err)
		return
	}
	if err := p.SendText(ctx, chatID, text); err != nil {
		ctx.Logf("%s reply failed: %v", p.Name(), err)
	}
}

func replyCard(ctx *sdk.Ctx, chatID string, c card) {
	p, err := activeProvider(ctx)
	if err != nil {
		ctx.Logf("reply skipped: %v", err)
		return
	}
	if err := p.SendCard(ctx, chatID, c); err != nil {
		ctx.Logf("%s card reply failed: %v", p.Name(), err)
	}
}
