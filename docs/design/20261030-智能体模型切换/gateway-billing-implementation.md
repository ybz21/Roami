# 默认智能体网关记账：V1 实现与验收

基线：`5d66fbe8`；分支：`feat/agent-gateway-billing`。本次实现直接使用 OpenCode、Claude Code、Codex、Pi、Roami，不新增接入身份。设计入口：[HTML](gateway-billing.html)。

## 最新交互修订

按用户后续要求，密钥完全由内部管理。移除独立密钥标签、密钥尾号、换发/停用/复制界面；模型页只展示来源与模型。网页目录不返回下游密钥状态，网页路由不再代理密钥管理接口；Go 私有接口继续支持内部维护。费用仍按默认智能体自动归集，原有本地源 API Key 配置保留。下方初次验收中涉及手工密钥界面的内容是本次修订前的历史记录。

修订验收：前端 158 文件 / 1163 测试通过，typecheck / i18n / hover / production build 通过；网关与 server Go 测试通过。桌面目录只有模型、用量与限额、模型定价三个标签，目录响应不含 agentKeys，网页密钥接口为 404。Android 真机确认无密钥入口、尾号与横向溢出，点按用量标签仍可查看既有按智能体账目。截图：`/tmp/gateway-hidden-keys-desktop.png`、`/tmp/gateway-hidden-keys-phone.png`。


## 产品与用户故事

- 已在 CLI 中配置模型服务的用户，可以在模型目录中显式导入本地源，再拉取全部模型。扫描不改原配置，凭据只在 Go 进程内读取、导入，不通过浏览器中转。
- 在智能体中应用模型时，自动写入本机网关地址和该默认智能体的 Key。模型源与模型仍是仅有的选择；显示 Key 尾号，不增加身份选择。
- 每个默认智能体可独立换 Key 或停用。已连接的原生配置随换 Key 更新；其他智能体不受影响。完整新 Key 仅返回一次，关闭弹层即从组件与 DOM 移除。
- 用量页按默认智能体筛选、汇总；换 Key 保持同一智能体的历史费用。来源、时间与现有全局限额继续使用原有入口。
- 未定价调用保留 Token、金额待核账；明确填写零价才表示免费。历史金额保留，后续改价不重算旧账。

## 技术设计与模块

### Key 与配置应用

`internal/modelgateway/agent_keys.go` 从现有 agent 注册表取得类型并加入内置 Roami。每类使用已有主密钥派生独立 HMAC 凭据，轮换增加 192 位随机代际；目录数据库保存代际、停用状态与过渡时间，不新增明文 Key 副本。管理列表只返回尾号。主密钥仍是受保护的本机秘密，能派生下游 Key；这与 HTML 中后续阶段的随机 Key 摘要存储方案不同，是复用现有配置自动写入机制的 V1 选择。

轮换先持久化新旧凭据的过渡状态，再通过 `agentproviders/gateway-key.go` 和既有 `apply.go` journal 写原生配置，成功后将旧 Key 设为 5 分钟有效。写入失败回退；中断后保留可重试的 pending 代际，界面显示“配置待确认”，避免旧配置因超时而断开。原生配置修订冲突先拒绝，不覆盖用户更改。

停用使后续鉴权失败，并唤醒准入队列重新检查 Key；已准入的调用继续结算。Roami 在使用目录网关时，其私有转发路径也遵守停用状态。

### 本地源导入

`agentproviders/local-sources.go` 读取既有保存方案，以及 Claude Code、Codex、OpenCode v1/v2、Pi 的原生源配置。支持明确的 API Key 与可解析的环境变量引用；不执行 helper、命令或 OAuth 流程。无法复用的凭据标为需手动配置。

`modelgateway/local_sources.go` 返回经过脱敏的预览，显式 POST 才导入。导入同时检查目录修订和源配置指纹；指纹覆盖原生修订、源字段与凭据，防止预览后变化。跳过指向本机网关端口的回环地址（包括 localhost / IPv6 变体），避免递归。相同地址但凭据不同的源不合并；已有同一源返回冲突提示。

### 账本与价格

`ledger.go` 的版本 3 迁移添加 `agent_kind`、`key_id`、`source_id`、`route_id`、`price_status`。历史 CLI 角色映射回默认智能体，原模型、请求 ID、金额与已存价格保持不变。其他原有内部调用继续归 Roami。

每次真实上游尝试保存来源、路由、Key 代际与价格快照。查价顺序为对外路由价、来源/原始模型价、原始模型或前缀价、默认价。新节点没有默认价时使用未定价状态；旧的已保存默认零价保持原语义。

`statistics.go` 在服务端筛选全部统计、小时明细与最近记录。智能体归属取自 Key，不采用客户端归账 header。原有全局 Go 准入与账期规则保留，不增加 Python 侧限额。

### 界面与接口

- `AgentGatewayKeys.tsx`：默认智能体列表、换 Key、停用、一次性复制与费用跳转。
- `LocalModelSources.tsx`：源预览、显式导入；手机复用全屏二级页。
- `GatewayModelBinding.tsx`：自动 Key 提示与尾号。
- `ModelProxySettings` / `ModelUsageStatistics`：智能体过滤与费用分组，复用既有图表、核账和限额设置。
- 新增私有管理接口：`GET /keys`、`POST /keys/:kind/rotate|disable`、`GET|POST /catalog/local-sources`；现有 usage 增加 `agentKind`。均在 `/agent/model-gateway` 下，经既有登录 API 代理，推理监听器不提供管理入口。

V1 的 Key 使用现有目录路由权限。按托管会话自动签发临时 Key、租约、单独的路由授权属于后续阶段；共享 CLI Key 的会话、内部子智能体不会被声称为独立账单。

## 验收

- `scripts/dev/quality/check.sh quick`、`full`：通过；通过隔离入口运行，Python 无相关改动，按规则跳过。
- 前端 typecheck、i18n、hover、build：通过；4777 个 locale key。Vitest：158 文件、1165 测试通过。
- 提交钩子曾遇到既有父进程生命周期测试的 `unix.Poll` EINTR；单独连续重跑 3 次及完整钩子重跑通过，未修改该测试。
- Go 网关 / 原生配置适配器：测试通过；`go test -race ./internal/modelgateway ./internal/agentproviders` 通过。
- 回归覆盖：5 类 Key 与管理端口隔离、修订冲突、原生配置更新、旧 Key 过渡与停用、pending 重启恢复、排队请求撤销、来源凭据与 header 隔离、历史账目迁移不改金额、本地源显式导入/环境变量变化/回环递归阻断、未定价与明确零价区分。
- 独立实例 `/tmp/roami-gateway-billing-test20261101`、模拟上游端口 18466；只调用本任务的固定响应服务，没有付费模型推理。
- 模拟账目：OpenCode 两笔已知费用 CNY 4.00、另有一笔未定价；Codex 一笔 CNY 2.00。共 4 次、4,500,000 Token，已知金额 CNY 6.00。OpenCode 换 Key 前后同一智能体归账；停用后请求为 401，账目不变。
- 桌面实测导入本地源、拉取 3 个模型、应用到 OpenCode、换 Key、按智能体查费用；MCP 配置保留，原上游 Key 没有写进下游网关方案。
- Android Redmi Note 8（216d6a43）：ADB 实际点按换 Key、停用、启用与费用跳转；确认按钮稳定态高 44 CSS px。无文档横向溢出，正文在内部滚动，顶部栏和底栏保留。ADB 滑动使内容 scrollTop 从 0 增至 454.5，document scrollTop 保持 0，视口与文档宽度均为 392 CSS px。

临时截图不提交主分支：`/tmp/gateway-billing-keys-desktop.png`、`/tmp/gateway-billing-usage-desktop.png`、`/tmp/gateway-billing-keys-phone.png`、`/tmp/gateway-billing-usage-phone.png`。此处验收为隔离实例，生产服务未部署本次改动。
