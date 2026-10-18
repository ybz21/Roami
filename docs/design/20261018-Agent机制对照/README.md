# Agent 机制与 Pi 对照审计

日期：2026-10-18。Roami 基线 `1ef1fa8`；Pi 基线 [`482c138`](https://github.com/earendil-works/pi/tree/482c1381a00d8d00bc81697e4a980c593db6803e)。本次矩阵记录固定基线的实现审计和待确认建议。审计后仅实施用户另行确认的 75% 自动压缩，并同步对应设计；其他差距没有据此自动修改。

入口：[交互 HTML 报告](index.html) · [完整矩阵](mechanisms.json) · [5 个隔离探针](probes.json)。工程记录使用中文，产品 i18n 不在本次修改范围。

## 结论

共核对 32 项机制：8 项已有核心能力、18 项部分具备、5 项产品扩展、1 项主动取舍。状态不是功能完成百分比；“具备”也不声称与 Pi 全部细节一致。

主要差距集中在异常写结果、真实溢出恢复、长回合与增量摘要、运行中插话、模型容量元数据。长期记忆、项目路由、tmux/外部编码 Agent、通知红点是 Roami 产品层需求，不能机械替换成 Pi 的默认行为。

## 比较层次

- `pi-ai`：模型协议、模型元数据和流式事件。
- `pi-agent-core`：工具循环、并发、steering/follow-up 和钩子。
- `pi-coding-agent`：会话、压缩、内置工具、MCP、技能和交互入口。
- `pi-durable`：当前版本另有持久化任务、子任务、fork、checkpoint 等；官方标记 Experimental。不能将基础 CLI 没有默认子智能体，解释成整个 Pi 仓库没有这些机制。

## 已复现问题

探针全部使用独立临时 SQLite、合成模型或 HTTP MockTransport；写效果仅为内存列表变化。没有读取生产对话、调用真实外部写接口、重复发送用户任务或变更部署。比较源码和运行探针是两种证据；没有运行 Pi 的完整测试，也没有进行两框架同条件性能对跑。

| 编号 | 优先级 | 问题 | 本轮观察 |
| --- | --- | --- | --- |
| F01 | P1 | 写响应超时被记为确定失败 | 合成写效果发生 1 次，随后 ReadTimeout；tool.state=failed，后续模型请求继续。 |
| F02 | P1 | 写完成后输出过大也记为失败 | 合成写效果发生 1 次，返回过大；tool.state=failed，turn 仍可完成。 |
| F03 | P1 | 记忆检索仍以字节冒充 tokenEstimate | 200 汉字：tokenEstimate=600；Pi 字符估计=50。50 不是中文真实 tokenizer 计数。 |
| F04 | P1 | 长工具回合超限后不能继续 | 60,000 字符的成功只读工具结果，在 10,000 输入 token cap 下导致 CONTEXT_TOO_LARGE。 |
| F05 | P1 | 供应商上下文溢出未触发恢复 | 上下文溢出 400 被映射 MODEL_HTTP_400；请求 1 次，压缩任务 0。 |

F01/F02 是自有结果确定性协议的缺陷，不声称 Pi 自动保证所有外部写的 exactly-once。重试风险是推断，未观测到真实重复写。

## 源码对照矩阵

| 机制 | Pi 层与行为 | 当前实现 | 结论与下一步 |
| --- | --- | --- | --- |
| M01 供应商与模型协议 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/ai/README.md)：pi-ai 提供多供应商适配和统一模型协议。 | [实现](../../../agent-runtime/src/roami_agent/providers/chat_completions.py)：当前只有 OpenAI-compatible Chat Completions；支持显式 Main/Worker 路由及配置指纹。 | 部分 / P2。先保留当前服务适配；需要原生 Anthropic/Responses 等协议时增加独立 provider，不能只替换 URL。 |
| M02 模型窗口与输出预留 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/models.md)：模型元数据携带 contextWindow/maxTokens。 | [实现](../../../agent-runtime/src/roami_agent/server/configuration.py)：输入 token cap 已生效；模型窗口可选、默认为未知，窗口/预留目前是全局运行时配置。 | 部分 / P1。按 Main/Worker 各自模型绑定已核实窗口与输出上限；避免切模型后沿用错误容量。 |
| M03 工具循环与上下文投影 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent-loop.ts)：模型响应、工具执行、后续响应分阶段循环，并允许转换模型上下文。 | [实现](../../../agent-runtime/src/roami_agent/core/loop.py)：Loop 已通过 ports 隔离；每次模型请求重建持久化投影，工具结果回到下一轮。 | 具备 / 保留。保留分层与持久化，不为对齐包名重写。 |
| M04 工具并发 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent-loop.ts)：当前 Pi 支持并发与串行批次，工具可要求顺序执行。 | [实现](../../../agent-runtime/src/roami_agent/core/loop.py)：同一次模型响应的工具全部依次 await；独立 Worker 任务可并发。 | 部分 / P2。优先考虑无冲突只读工具并发；写操作、同资源操作继续串行，并保持结果顺序。 |
| M05 Steering 与 follow-up | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent.ts)：运行中 steering 和自然结束后的 follow-up 分开排队。 | [实现](../../../agent-runtime/src/roami_agent/conversation/mailbox.py)：Main 同分支输入按 turn 排队；/stop 可中断，任务有 revision/steer，但不是同一套中途插话语义。 | 部分 / P1。设计继续追问、立即改意图、稍后追加三种输入；在安全边界消费，避免快问快答被长工具阻塞。 |
| M06 正文流与事件重放 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent-loop.ts)：agent-core 提供模型与工具生命周期事件。 | [实现](../../../agent-runtime/src/roami_agent/server/http.py)：正文首段落盘并 SSE 推送；支持 cursor/Last-Event-ID、断线重放、持久化调用链。 | 具备 / 保留。保留 Go 统一入口和事件落盘后推送。 |
| M07 思考与工具参数增量 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/ai/README.md)：提供 thinking 与 tool-call 参数等增量事件。 | [实现](../../../agent-runtime/src/roami_agent/providers/chat_completions.py)：主要暴露正文流；工具参数在完成后汇总，未统一 thinking 事件和显示策略。 | 部分 / P2。增加标准事件类型与兼容策略；只展示供应商公开返回的内容。 |
| M08 参数校验与错误回传 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/agent/src/agent-loop.ts)：工具参数解析、校验、执行结果进入循环。 | [实现](../../../agent-runtime/src/roami_agent/tools/registry.py)：JSON Schema 校验、工具可见范围和结构化错误已存在。 | 具备 / 保留。保留；补齐错误的结果确定性分类，见 M10。 |
| M09 大输出与产物外置 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/tools/truncate.ts)：内置文件/Shell 工具有有界输出与截断策略；输出大小限制与 token 窗口分开。 | [实现](../../../agent-runtime/src/roami_agent/tools/registry.py)：Shell/MCP/文件已有产物外置；通用工具超出 128 KB 时仍直接报错，HTTP 也有直接截断失败路径。 | 部分 / P1。统一摘要/截断/产物引用协议；完成动作后不要因为输出大而谎报动作失败。F02 已复现。 |
| M10 写效果未知与重试 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/README.md)：durable 提供任务生命周期；外部效果的幂等/确认仍取决于工具实现。 | [实现](../../../agent-runtime/src/roami_agent/tools/gateway.py)：CLI/MCP 对部分未知结果有专门处理；通用 HTTP/工具错误会把部分写结果记为 failed。 | 部分 / P1。先补 write 的确定失败、执行成功但回执缺失、未知三分法；未知不得自动重放。F01/F02 已复现，不声称 Pi 保证外部 exactly-once。 |
| M11 token 估算和 usage 校准 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/compaction/compaction.ts)：有效 usage 加后续字符估计；无 usage 使用 chars/4；图片采用占位估计。 | [实现](../../../agent-runtime/src/roami_agent/context/token_estimate.py)：请求准入、上下文面板与 /status 已使用统一机制，计入系统提示、工具及结果。 | 具备 / 保留。保持“预估”标签，字符估计不是模型 tokenizer；保留真实 usage 校准。 |
| M12 失效旧 usage | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/compaction/compaction.ts)：压缩/上下文编辑后的旧计数不再直接使用。 | [实现](../../../agent-runtime/src/roami_agent/context/projection.py)：请求配置、来源前缀指纹、snapshot、memory epoch 校验；模型/工具/历史变更后回退估算。 | 具备 / 保留。保留；已测试模型切换、编辑、压缩及遗忘。 |
| M13 供应商溢出与截断恢复 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/agent-session.ts)：coding-agent 区分上下文溢出与可恢复的长度截断，限制压缩重试次数。 | [实现](../../../agent-runtime/src/roami_agent/providers/chat_completions.py)：目前请求前预估；供应商上下文溢出 400 仅映射 MODEL_HTTP_400，length 终止直接失败。 | 部分 / P1。安全提取错误类别后压缩并有限续答；不得输出原始错误体或重放写工具。F05 已复现。 |
| M14 长工具回合与切分 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/compaction/compaction.ts)：支持部分长回合的分段摘要，并选择合法边界。 | [实现](../../../agent-runtime/src/roami_agent/context/projection.py)：只切完整轮次；正在进行的工具回合过大时无法压缩，直接拒绝。 | 部分 / P1。为已完成工具阶段设计安全切点，并配合大结果外置；保留调用/结果配对。F04 已复现。 |
| M15 增量摘要 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/compaction/compaction.ts)：可带上 previousSummary 更新新历史。 | [实现](../../../agent-runtime/src/roami_agent/context/projection.py)：当前摘要请求仍构造所选原始前缀；重复压缩可能反复发送很长的旧历史。 | 部分 / P1。改为有效旧摘要加新增待压缩片段；保留来源指纹和遗忘失效校验。此项是源码推断，未压测供应商极限。 |
| M16 追加历史与分支 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/session-manager.ts)：coding-agent 支持会话树与分支投影；durable 也有 conversation/fork。 | [实现](../../../agent-runtime/src/roami_agent/conversation/transcript.py)：SQLite 追加消息、祖先分支投影及 fork 已实现；仅允许安全的完整助手回复点，未提供同等完整的树导航。 | 部分 / P2。保留安全 fork；若需要自由切换历史分支，再补树和分支摘要入口。 |
| M17 输入幂等与事务事件 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/README.md)：durable 把接收、状态和可见事件建立在提交之上。 | [实现](../../../agent-runtime/src/roami_agent/storage/database.py)：请求键校验、SQLite 单写队列、事务事件、日志重放与备份已有实现。 | 具备 / 保留。保留；不能把不同持久化技术当成缺失功能。 |
| M18 断点与重启恢复 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/README.md)：durable 有 phase checkpoint、睡眠和故障停泊等机制；该包标记 Experimental。 | [实现](../../../agent-runtime/src/roami_agent/conversation/transcript.py)：运行中 turn 中断、未决工具 unknown；编码任务通过 Go 外部 runner 核对，具备部分恢复。 | 部分 / P2。当前保守恢复合理；需要原生任务逐阶段恢复/崩溃停泊时另做状态协议，不照搬实验 API。 |
| M19 Main/Worker 与父子任务 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/README.md)：基础 CLI 的子智能体通常由扩展提供；durable 包已有子任务和 subagent 机制。 | [实现](../../../agent-runtime/src/roami_agent/dispatch/tasks.py)：原生 Worker、父子关系、深度与预算、结果回主对话已实现。 | 扩展 / 保留。保留产品调度；后续补更完整 DAG 依赖/检查点时参考 durable，但不声称 Pi 没有子任务。 |
| M20 Codex/Claude 与项目派活 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/README.md)：Pi 提供扩展/执行宿主接口；不是 Roami 项目与 tmux 会话管理器。 | [实现](../../../agent-runtime/src/roami_agent/executors/roami_cli.py)：统一 Go CLI 接入已有会话、新散会话、项目 worktree、新项目，入队/送达/结束/核验分开。 | 扩展 / 保留。保留；旧会话的自动完成回报仍须真实生命周期回调。此前 12 场景验收记录仅作已有证据，本轮未重跑外部 Agent。 |
| M21 取消与资源租约 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/README.md)：durable 区分取消等待与取消任务，并建立任务所有权。 | [实现](../../../agent-runtime/src/roami_agent/dispatch/resource_leases.py)：/stop、任务取消、进程组停止、lease/epoch 和执行回执按不同边界处理。 | 具备 / 保留。保留层次；通用写工具异常分类仍需 M10 补齐。 |
| M22 任务/对话/每日记忆 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/skills.md)：技能和项目上下文不等同于 Roami 所需的长期记忆业务。 | [实现](../../../agent-runtime/src/roami_agent/memory/records.py)：来源、scope、候选确认、每日整理、FTS 检索和遗忘传播已存在。 | 扩展 / 保留。保留自有记忆层；目前是词法检索，不能宣传为 embedding 语义召回。 |
| M23 检索长度口径 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/src/core/compaction/compaction.ts)：Pi 的字符 token 估计与请求上下文预算具有明确单位。 | [实现](../../../agent-runtime/src/roami_agent/retrieval/memory_search.py)：检索命中的 tokenEstimate 仍是 len(body.encode())；200 汉字样本报 600，当前字符估计为 50。 | 部分 / P1。统一 tokenEstimate 或明确改名 bytes；50 仅是 Pi 字符估计，不是中文真实分词。F03 已复现。 |
| M24 前缀、会话身份与协议 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/ai/README.md)：pi-ai 有供应商适配；durable 保留各会话 provider identity。 | [实现](../../../agent-runtime/src/roami_agent/providers/request_policy.py)：已有稳定配置指纹、显式 cache 能力开关与 usage；实际参数采用当前兼容服务的字段。 | 部分 / P2。逐供应商验证字段和会话 affinity；观察真实 cache usage，不凭打开开关宣称命中。 |
| M25 连接、暴露与认证 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/mcp.md)：当前 coding-agent 有 MCP 配置、暴露和认证机制；不能沿用“Pi 无 MCP”的旧结论。 | [实现](../../../agent-runtime/src/roami_agent/tools/mcp.py)：支持配置的 stdio/HTTP MCP、结果外置、进度与未知结果处理，主要作为 Worker 工具加载。 | 部分 / P2。补按需发现/启用策略；OAuth/动态管理按实际需求实现，不直接向 Main 塞全部 schema。 |
| M26 技能发现与按需加载 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/skills.md)：SKILL.md frontmatter、渐进加载、附属资源和命令入口。 | [实现](../../../agent-runtime/src/roami_agent/tools/worker_catalog.py)：启动扫描根目录、skill_read 按名读取；尚未等同于完整元数据索引、reload 与命令暴露。 | 部分 / P2。先补 description 元数据与版本刷新；继续限制目录来源。 |
| M27 生命周期钩子与热加载 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/extensions.md)：有模型请求、工具前后、上下文和会话等扩展机制。 | [实现](../../../agent-runtime/src/roami_agent/protocol/ports.py)：内部 ports 可替换依赖，工具注册可扩展；尚无同等公共扩展 ABI/热加载生命周期。 | 部分 / P2。内部模块足够时保持简洁；需要第三方插件再定义 versioned hooks。 |
| M28 斜线命令与历史操作 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/rpc.md)：coding-agent/RPC 的模型、会话、压缩和运行控制接口更多。 | [实现](../../../agent-runtime/src/roami_agent/protocol/commands.py)：已提供 compact/status/tasks/memory/stop/help；模型切换走输入卡，历史另有界面入口。 | 部分 / P2。优先考虑 /new、/model、/context、/retry 的明确语义；retry 必须受未知写结果约束。 |
| M29 Browser/Computer 与人工接管 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/coding-agent/docs/extensions.md)：通过工具和扩展接入宿主能力。 | [实现](../../../agent-runtime/src/roami_agent/dispatch/resource_controls.py)：观察、lease/scene epoch、截图来源、坐标、接管与恢复有专门实现。 | 扩展 / 保留。保留资源协议；不能从租约存在推断任意页面/桌面任务都已验收。 |
| M30 主动消息、红点与提醒 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/README.md)：durable 提供持久化调度和睡眠基础，产品通知由宿主构建。 | [实现](../../../agent-runtime/src/roami_agent/replies/delivery_outbox.py)：持久化回报、未读确认、主动建议、提醒、每日简报和回原会话已实现。 | 扩展 / 保留。保留；投递不确定状态和用户看见/读过必须分开。 |
| M31 Go 统一鉴权与进程隔离 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/README.md)：Pi CLI 默认继承宿主权限，不等于内建强隔离。 | [实现](../../../agent-runtime/src/roami_agent/tools/process.py)：Go 统一鉴权、私有本地服务、工作区路径检查与密钥环境过滤；Shell argv 仍继承系统用户能力。 | 取舍 / 保留。保留 Go 入口；cwd/root 校验和 lease 都不是 OS 沙箱。需隔离时另接容器/系统沙箱。 |
| M32 已有测试与本轮证据 | [源码](https://github.com/earendil-works/pi/blob/482c1381a00d8d00bc81697e4a980c593db6803e/packages/durable/README.md)：Pi 有自身测试和检查点/事件机制；本轮没有运行其完整测试。 | [实现](../../../agent-runtime/src/roami_agent/observability/prompt_manifests.py)：当前已通过 420 个 Python 与 635 个前端测试；本轮额外执行 5 个隔离探针。 | 具备 / 保留。保留证据分级：源码比较、既有测试、本轮复现，不能写成同条件性能实测。 |

## 建议实施顺序（待确认）

1. **结果真实**：先修 F01/F02 的写结果确定性、大输出回执，以及 F03 的记忆长度单位。
2. **长会话稳定**：修 F05 的溢出类别和单次恢复；补 F06 增量摘要；再设计 F04 的安全切分和 F08 的各角色容量。
3. **快问快答**：明确 F07 的 steering/follow-up 后，再做只读并发、工具参数增量、命令与模型交互。
4. **按需求扩展**：原生多供应商协议、MCP OAuth/动态暴露、技能/插件热加载和通用 checkpoint；不为了与 Pi 功能列表相同而增加无用复杂度。

实施上述建议前，应先确认会改变交互或已批准架构的部分，再更新原设计和代码。本次没有把建议写成已通过设计，也没有宣称已修复这 5 个问题。

## 既有验证与局限

上一实现基线已有 420 项 Python、635 项前端测试通过，另有 12 场景委派验收与真实模型 token 校准记录。本轮新增的 5 个探针是专项检查，没有重跑 Codex/Claude 真实委派矩阵，也没有证明 Browser/Computer 能处理任意站点/桌面任务。字符数 / 4 是近似，中文样本预估偏差仍须依赖实际 usage 校准。存储/上传/进程输出的字节上限与上下文 token 预算是不同概念，前者仍可合理保留。

## 复现方式

从仓库根目录运行（使用临时数据库与合成工具，不读取生产状态）：

```bash
uv run --frozen --directory agent-runtime python ../docs/design/20261018-Agent机制对照/probe_mechanisms.py
```

脚本断言五个当前行为均可观察到；这是确认差距的审计探针，不是声称这些错误行为应该成为产品契约。修复后应更新探针预期，正式回归测试放回 `agent-runtime/tests/`。

## 审计后的单项确认：75% 自动压缩

用户在审计期间明确确认了容量 75% 的自动压缩触发线。此项单独实现并同步原设计；本报告矩阵继续保留审计基线，其他 8 项补齐建议没有据此自动获得实施确认。该初版曾按输入 cap 回退，已被用户否决；新修订取消默认容量与固定 cap，按当前模型真实窗口 × 75%，未知保持未知。Main 的服务元数据位于 token_limits.context_window，实际为 1,048,576，对应触发线 786,432；Worker 未返回窗口，不能猜测。请求前检查，回复完成后的 usage 再检查并排队后台压缩；软线内暂无安全切点不拒绝输入。

旧版真实模型隔离验收（历史证据，不代表修订后的容量政策）：临时配置输入 cap=8,800、75% 触发线=6,600；模型 usage=6,724 后，答案先完成，压缩任务处于 queued，未内联生成摘要。显式执行后台摘要后降至 2,037，原始 2 条消息保留，供应商总请求 2 次（回答 + 摘要）。生产 cap 不随此测试改变。见 [threshold-results.json](threshold-results.json)。

## 工具结果专项

见 [HTML 专项报告](tool-results.html)。本次核对文件读取、Shell、MCP、图片、持久化投影和工具配对。统一结果外置、UTF-8 分页和写结果确定性属于待确认建议，本次没有据此修改工具执行协议。

模型容量修订真实验收：[capacity-results.json](capacity-results.json)。从当前服务读取 Main 窗口 1,048,576，触发线 786,432；隔离真实推理 usage=26,270，超过旧 24K，未创建自动压缩任务，2 条原始消息保留。1M 边界前后通过合成 usage 回归验证，没有发送近百万 token 的真实请求。Worker 容量仍未知。
