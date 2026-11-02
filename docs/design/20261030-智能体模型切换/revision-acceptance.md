# 统一模型列表修订验收

2026-10-31。取消“对外模型”与发布流程，模型保存后直接进入所有使用场景共用的目录。

## 自动化

新增回归覆盖：模型保存直接写入可用模型集合，无需公开标识或发布；随后重新进入 Codex 模型页面，可在选择器中找到刚添加的模型；显示名称选填，留空使用服务商模型 ID。默认入口打开模型列表，列表不显示内部 ID 或发布状态。原定价保存和目录故障时仍可设置价格的回归继续保留。

前端 typecheck、i18n、hover、完整 Vitest 和生产构建作为本次完成门禁。本次仅修改前端与文档，未修改 Go、Python、依赖或数据库。

## 运行验证

通过 `scripts/dev/isolated-roami.sh /tmp/roami-model-hub-run` 启动隔离实例，复用独立数据和 CLI 配置目录；不修改用户真实模型配置。模型源使用本地测试地址，不产生外部消费。

- `npm run typecheck`、`npm run i18n:check`（4503 keys）、`npm run hover:check`、完整 Vitest（149 文件、1121 测试）与生产构建均通过。
- 桌面实际添加“全场景验收模型”，只填写显示名称和服务商模型 ID，保存时没有发布步骤；随后进入 Codex 直接选到并应用。当前默认模型摘要显示名称，不展示内部路由 ID。
- Redmi Note 8 实际 ADB 点按选择 Chat 来源，输入 `fixture-mobile`，显示名称留空，保存后模型列表显示 `fixture-mobile`。通过能力分类切到 Roami，主智能体选择器立即包含该模型，无需发布或复制连接。
- 同时使用桌面和手机遇到目录版本冲突时，点击“重新读取”后仍保留已输入的 `fixture-mobile`，再次保存成功；没有覆盖桌面刚添加的模型。
- 实际页面 `scrollWidth <= innerWidth`、文档 `scrollTop=0`；二级页保持单返回栏和四项底部导航，选择器和选项为 44px。
- 再次读取原定价与限额：默认 11/30/1、逐模型 12/32/1.2、每日限额 80 CNY、Asia/Shanghai，均与上一轮保存值相同。

## 产物

- [新版操作视频（MP4，约 16 秒）](/api/file/tmp/model-hub-simplified-demo.mp4)：实际添加、在 Codex 选择并应用，再展示保留的定价。录制器压缩静止等待，已解码检查，1280×800、147 帧。
- [新版桌面截图](/api/file/tmp/model-hub-simplified-desktop.png)
- [Android 刚添加的模型可供 Roami 选择](/api/file/tmp/model-hub-simplified-phone.png)

只清理本任务隔离实例和 19557 ADB 转发；源码和设计文档保留在当前 worktree，未提交一次性媒体文件。

## Claude Code 真实接入与安装补验

用户要求优先交付本机 CC，补验和修改如下。

### 本机真实配置

- 本机已有 Claude Code 2.1.314，无需重复安装。按当前 Roami 保存的真实连接，将 CC 用户配置设为已保存的上游与 `deepseek-4.1-flash` 模型，使用 Bearer 认证。此次真实配置直接使用现有上游，不依赖会在验收后关闭的临时网关；没有替换正在运行的 Roami 主服务。
- 经现有 `agentproviders.Store` 的保存、备份、原子应用和读回验证，配置记录为 `Roami · deepseek-4.1-flash`。保留已有 hooks、插件、权限等非模型字段；Codex 用户配置未改动。
- 同步设置 `ANTHROPIC_MODEL`、Sonnet/Opus/Haiku 默认映射，清理旧的认证 helper 与替代模型列表，启用网关模型发现。原配置、helper 和模型列表进入恢复备份；已存在旧版备份时，新增接管字段也补充备份。
- 本机 `blade-models-sync.timer` 每 30 秒同步一次，会覆盖 CC 凭据与模型目录。在本机同步脚本加上 CC 专属所有权判断：`ROAMI_MODEL_MANAGED=1` 时跳过 CC 写入，Pi / OpenCode 原同步继续执行。脚本原稿已备份在其私有 `backups` 目录；恢复原 CC 配置会移除标记，从而恢复原同步行为。脚本语法检查通过，后续多个同步周期 `changed=[]`，CC 的 Bearer 凭据和模型保持。
- 真实 `claude -p` 读取用户配置，无临时模型覆盖，返回 `CC_CONNECTION_OK`，JSON 为 `subtype=success`、`is_error=false`。验证时禁用工具和 MCP、禁止会话持久化。

### 新版网关真实链路

独立实例中配置相同真实上游的 Messages 模型，再从 CC 页面使用的应用 API 写入独立 `CLAUDE_CONFIG_DIR`。实际 Claude Code CLI 经回环网关返回 `CC_GATEWAY_OK`。账本记录 `role=cli_claude`、实际模型 `deepseek-4.1-flash`；该上游此次流式用量报告为 0，因此本地记录金额为 0，不能据此声称没有外部消费。没有硬编码临时模型替换 Roami 的主/后台路由。

### 安装与界面

- 智能体模型详情现在直接展示安装状态、版本及安装/升级动作，调用既有真实安装 API；其它四种 CLI 的配置能力保留。
- 新回归覆盖从缺失状态的 Claude Code 模型页面确认安装，再调用安装 API；不为验收卸载或重装用户已安装的 CC。
- 桌面和 Redmi Note 8 打开 CC 模型详情，真实显示已安装版本、所选模型和当前默认模型。手机 ADB 点按升级打开确认并取消，没有执行升级。补齐确认按钮的粗指针高度为 44px。
- Go 全仓快速质量门禁、`agentproviders` 与 `modelgateway` 回归和 race 检查、前端 typecheck / i18n / hover / 完整 Vitest / 生产构建通过。前端 149 文件、1122 测试；Go 新回归覆盖默认模型档位、旧 helper/模型目录清理、既有备份升级及恢复。

[本机 CC 与网关实际请求回执（JSON）](/api/file/tmp/roami-cc-verification.json) · [CC 桌面页面](/api/file/tmp/roami-cc-desktop.png) · [CC 手机页面](/api/file/tmp/roami-cc-phone.png)

协议与配置参考：[Claude Code 连接网关](https://code.claude.com/docs/en/llm-gateway-connect)、[网关兼容性](https://code.claude.com/docs/en/llm-gateway-protocol)。本次真实上游先分别验证了认证方式，`x-api-key` 返回 401，Bearer 返回 200；CLI 成功回执取自配置生效后的真实请求。

CC 补验最终产物：[CC 配置与升级入口录屏](/api/file/tmp/roami-cc-demo.mp4)。最后生产构建完成，手机升级确认和取消按钮实测均为 44px，可真实点按；未触发已安装 CC 的升级。

验收结束后清理独立实例及其中含临时真实上游凭据的配置目录，真实用户 CC 配置和所有权保护继续保留。
