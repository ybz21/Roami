# 本地模型代理与每日限额

## Product Design

2026-10-29 修订：在 Roami 进程内运行 Go 模型网关，Agent 的模型 HTTP 请求先经过本地记账和准入，再转发到原配置的云网关或模型服务。模型连接地址和密钥继续由既有模型设置管理。模型与连接页恢复「模型连接 / 代理与计费 / 模型单价」三个标签，使用本地 Go 账本；同时提供 CLI 和受现有登录保护的管理 API。本地统计与价格不依赖云端账单接口。

本地金额是按本机配置单价计算的消费账本，不发起云端余额扣款，不把上游已有账单再相加。未配置单价时使用默认价；默认价为零。初始币种 CNY、时区 UTC、无限额，设置价格和限额后对新请求生效。外部专业 CLI 继续使用它们各自的模型连接。

## User Stories

- 作为使用者，我能在本机配置每百万输入、输出、缓存读取 token 的价格，以及按指定时区重置的每日金额限额。
- 主对话、后台任务、记忆和宿主机评测使用同一个本地入口，共享每日账本；容器评测沿用宿主机桥接，由宿主机请求同一本地 Go 网关。
- 我能查看最近 1–90 天按日期、连接角色、模型和币种分组的请求数、token 和金额，以及最近 20 笔请求的状态。`usageUnknown` 单独标明缺失 token 的请求，人工核账后仍不伪造 token 数。评测请求保留已有评测角色、会话和请求标识。
- 上游缺失用量、断流或进程崩溃时，非零单价请求保留费用未知状态；核对真实金额并填写理由后可以恢复额度准入。

## Technical Design

```text
configured_provider / 宿主机评测模型
  -> LocalGatewayTransport (httpx，私有 Unix socket)
  -> internal/modelgateway.Handler
     -> Ledger.Admit：事务检查每日消费并持久化 pending
     -> 原模型地址：转发请求及流式响应
     -> Ledger.Settle：解析最终 usage，按请求接纳时的单价结算

roami agent gateway / 已认证 Web API
  -> 同一个 Go 网关 socket
  -> 价格、限额、统计、未知费用核账
```

模块划分：`configuration.go` 校验设置并做整数金额换算；`pricing.go` 复用云网关的价格选择规则；`ledger.go` 负责迁移、配置、准入和幂等结算；`usage.go` 增量解析 OpenAI chat-completions 的 JSON/SSE usage；`statistics.go` 提供一致快照；`handler.go` 管理 HTTP 边界和转发；`service.go` 管理私有 socket、进程锁和关停。

定价核心源自 `~/codes/llm-gateway/internal/observe/pricing.go`，版本 `1f1ffc1ab080c0da935d063ac79380d2f2a4a079`。保留精确模型、前缀、默认单价的优先级，并将重叠前缀改成确定性的最长前缀匹配。本地累计金额使用十亿分之一币种单位的整数；单笔采用有理数计算并四舍五入。OpenAI 的输入 token 含缓存部分，计算普通输入费时先减去缓存，再单独计算缓存价。

本地账本注册到统一存储目录：`<DatabaseRoot>/models/gateway.db`，catalog ID 为 `model-gateway`，owner 为 `go-model-gateway`，随统一数据库备份和迁移处理。旧 Python `model_proxy_calls` 继续仅作历史账本，不参与新额度计算。

Go launcher 在启动 Python 前开启网关，注入 `ROAMI_MODEL_GATEWAY_SOCKET`；Web supervisor 和 `roami agent serve` 共用相同生命周期。socket 权限 0600，路径与 Agent socket 等长，保留长路径回退能力。持久文件锁防止两个网关互相恢复在途记录；重启将非零价格的 pending 请求标记 unknown。关停先取消网络请求、等待结算，再释放进程锁。网关不可用时，已配置本地 transport 的客户端不回退直连。直接运行开发用 Python、没有 launcher 环境时保留原直连能力。

价格在准入时快照保存；更新价格不重算历史金额。启用每日限额后，同一天有 pending 或 unknown 就拒绝新的调用，分别返回 409；消费达到限额返回 402。检查和 pending 插入处于同一 SQLite immediate 事务，防止并发同时放行。限额是请求前准入线，最后一笔调用仍可能超额；不是按 token 中途截流。未配置限额时不限制并发。币种或时区不能在仍有未决账目或最近账期已有调用时更换，避免重新解释账期绕过限额。

仅持久化模型、角色、token、单价快照、金额、状态和已有不透明评测标识；不落请求正文、响应正文或密钥。SSE 逐块转发，解析缓冲有上限；收到合法终结 usage 和 DONE 后即保留已知费用，不因客户端先于 HTTP EOF 关闭而丢弃回执；模型等待期限沿用调用方配置，不叠加网关固定超时；缺失或非法 usage、未正常结束和服务端错误不记成免费。明确未连接成功、上游拒绝以及零单价调用可记零；HTTP 失败与费用未知分别保留。

## 使用

Web 入口为「设置 → 模型与连接 → 代理与计费 / 模型单价」，保留原统计图、日期选择、单价编辑和草稿恢复；最近请求可核对未知费用。正常启动新版本 `roami server` 或 `roami agent serve` 后，也可使用 CLI：

```bash
roami agent gateway settings
roami agent gateway configure --file /path/to/gateway.json
roami agent gateway usage --days 30
roami agent gateway reconcile --call <调用ID> --file /path/to/receipt.json
```

配置为完整替换，价格单位是所选币种 / 百万 token：

```json
{
  "currency": "CNY",
  "timezone": "Asia/Shanghai",
  "dailyLimit": 20,
  "pricing": {
    "default": {
      "input_per_million": 0,
      "output_per_million": 0,
      "cache_read_per_million": 0
    },
    "models": {
      "your-model": {
        "input_per_million": 2,
        "output_per_million": 8,
        "cache_read_per_million": 0.5
      }
    }
  }
}
```

`dailyLimit: null` 表示无限额；`0` 暂停新请求。示例单价仅展示结构，使用时填入实际价格。核账文件示例：`{"amount": 0.75, "reason": "已核对上游用量回执"}`；只允许核对 unknown 记录，保留原始错误与核账理由，不能覆盖已知消费。

| 方法 | 已认证 API | 内容 |
| --- | --- | --- |
| GET / PUT | `/api/agent/model-gateway/settings` | 读取 / 替换本地价格与限额 |
| GET | `/api/agent/model-gateway/usage?days=7` | 1–90 天分组及最近调用，0 为累计；day=YYYY-MM-DD 查询指定日及分时 |
| PUT | `/api/agent/model-gateway/calls/:id` | 核账未知费用 |

新增英文帮助仅出现在用户 shell，属于 i18n 规范的终端输出例外。Web 新文案提供中英文。原 `/agent/model-usage` 仍读取已归档的 Python 历史账，恢复的页面读取 `/agent/model-gateway/*`。

## Acceptance

验收记录：[本地 Go 网关](records/2026-10-29/local-go-gateway.md)、[恢复计费页面](records/2026-10-29/restored-billing-page.md)。

[设计修订与验收记录](records/README.md)
