# Roami 内置网关协议适配验收

2026-10-31。修正“按智能体协议重复配置来源”的问题：同一上游模型经 Roami 网关供 CC、Codex、OpenCode、Pi 和 Roami 选择。

## 自动化覆盖

- 三种协议两两转换，共六个方向，分别验证 JSON 和 SSE。检查 system 消息、工具 schema、调用 ID、参数、工具结果以及结束事件。
- 四类原生配置使用工具自己的协议连接网关，不再把上游协议写成客户端准入条件；所有类型均能看到同一份模型列表。
- CC 对话中的 system 消息、Codex 命名空间、自定义文本工具、图片输入及工具返回图片、可移植的思考文本、结构化输出保持对应关系。
- 不把厂商托管搜索伪造成可执行函数；自动模式移除无法提供的托管工具，告知模型并返回能力提示头，强制指定不支持的工具则拒绝。
- CC/Codex 默认附带的厂商专用思考配置不强加给另一类上游，避免普通模型因不支持该参数而拒绝请求；响应头明确标注。上游返回的可见思考文本仍可进入工具后续上下文。显式保存的 Chat 推理参数按对应字段转发。
- CC 的思考块先于正文块，JSON 与 SSE 上游均保留最终文本；正文后追加的思考明确拒绝，避免 CC 回执显示空白。
- 文本在上游结束前即可收到；完整协议结束事件后可完成响应，无需等待上游关闭连接。截断流不生成成功结束事件。
- 主备来源可使用不同协议，仅连接建立前失败才切换，每次尝试独立结算。
- 用量读取原始上游协议：示例输入 100、输出 7、缓存 20 在各转换方向均保持；价格使用真正调用的候选模型。无法转换的请求在准入前拒绝，不产生调用账目。

完整前端：153 个文件、1136 项测试通过。typecheck、i18n、hover、生产构建通过。仓库 full 质量门及 Go 网关、原生适配器 race 检查通过；本轮不涉及 Python 修改，按范围跳过 Python 检查。

## 真实客户端工具往返

使用一个本地确定性 Chat Completions 测试上游、一条来源和一个模型，原生客户端直连 Roami 回环网关。测试上游不调用外部模型；并非真实云模型的质量或全能力测试。

| 客户端 | 原生协议 | 验证结果 |
| --- | --- | --- |
| Claude Code 2.1.314 | Messages | 两轮完成 Bash 调用、写入 GW_TOOL_OK、回传工具结果并得到 GW_NATIVE_OK |
| Codex CLI 0.166.0 | Responses | 两轮完成 exec_command 调用、写入 GW_TOOL_OK、回传工具结果并得到 GW_NATIVE_OK |

两份独立工作目录各自生成文件。第二轮的上游请求保留工具调用 ID、工具结果及前一轮可见思考文本。Claude 回执中 is_error=false，Codex 回执 turn.completed，网关用量均可核对。

CLI 配置、账本及捕获日志均在 `/tmp/roami-gateway-adapter-run` 隔离目录。用户真实 CC 和 Codex 配置未改动。测试过程中先用本机代理查看请求结构，最终验证使用已保存的网关原生配置直接调用。

## 真实界面与 Android

主列表仅有“统一模型服务 / 主力编程模型”，正在使用同时显示 Codex 与 Claude。手机真实点按配置智能体、进入 CC 模型页和 Codex 模型页：两页的来源下拉均只有同一个“统一模型服务”，模型均为“主力编程模型”，显示已应用；不再要求来源协议匹配智能体。

Redmi Note 8，1080×2340、DPR 2.75。来源与模型选项、返回按钮均为 44px；模型搜索键盘弹出时，选项向上展开可点；文档宽 392、视口宽 392、scrollTop=0。顶栏、返回和底部导航保持可用。

## 交付证据

- [共享来源演示（MP4，约 22 秒）](/api/file/tmp/roami-gateway-shared-demo.mp4)
- [单一来源（手机）](/api/file/tmp/roami-gateway-shared-phone.png)
- [CC 使用此模型（手机）](/api/file/tmp/roami-gateway-cc-phone.png)
- [Codex 使用此模型（手机）](/api/file/tmp/roami-gateway-codex-phone.png)
- [CC 模型页（桌面）](/api/file/tmp/roami-gateway-cc-desktop.png)
- [Codex 模型页（桌面）](/api/file/tmp/roami-gateway-codex-desktop.png)
- [客户端验证摘要（JSON）](/api/file/tmp/roami-gateway-adaptation-verification.json)

录屏已解码检查，为 1280×800、111 帧、约 22 秒。临时实例和手机转发通过任务所属入口清理；测试密钥及捕获的请求不进入仓库。

协议范围与剩余限制见 [设计入口](README.md#适配边界)。提供商的加密思考状态、服务器会话和模型固有能力不凭协议转换获得；无法等价实现的内容明确拒绝。

## Roami 智能体品牌标修正（2026-11-01）

智能体目录中的 Roami 项改用既有 `RoamiLogo`，直接引用 `/logo-mark.svg`，保留 32px 尺寸及现有品牌标布局，无新增产品文案。桌面与 Redmi Note 8 均确认图片完整加载；手机实际点按管理进入 Roami 模型配置，页面宽 392、文档宽 392。完整前端仍为 1136 项通过，完整质量门通过。

[桌面改前](/api/file/tmp/roami-agent-logo-before-desktop.png) · [桌面改后](/api/file/tmp/roami-agent-logo-after-desktop.png) · [手机改前](/api/file/tmp/roami-agent-logo-before-phone.png) · [手机改后](/api/file/tmp/roami-agent-logo-after-phone.png)。所有截图使用隔离实例；测试结束后清理本轮实例与手机转发。
