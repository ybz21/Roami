// dingtalk.go 是钉钉 provider 的占位:接口面已就绪(Stream 模式长连接 +
// 机器人发消息),实现待接入 open-dingtalk/dingtalk-stream-sdk-go。
// 配置 im_provider=dingtalk 时给出明确指引而不是静默失败。
package im

import (
	"fmt"

	"github.com/ybz21/Roami/pkg/plugin/sdk"
)

type dingtalkProvider struct{}

func (dingtalkProvider) Name() string { return "dingtalk" }

var errDingtalkTODO = fmt.Errorf("dingtalk provider 尚未实现(接口见 plugins/im/provider.go,欢迎接入 Stream 模式 SDK)")

func (dingtalkProvider) Listen(_ *sdk.Ctx, _ func(Message)) error    { return errDingtalkTODO }
func (dingtalkProvider) SendText(_ *sdk.Ctx, _, _ string) error      { return errDingtalkTODO }
func (dingtalkProvider) SendCard(_ *sdk.Ctx, _ string, _ card) error { return errDingtalkTODO }
