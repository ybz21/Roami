# CLI 与 Roami 会话选模实现

本轮在统一设计上接通模型目录、CLI、Roami 原生会话与原生任务。网关工作区复用本机网关会话的生产实现（原提交 `5f99951a`），保留其来源、Key 与调用示例；没有改写另一个会话的工作区。

## 产品行为与用户故事

- 用户先在“能力 → 模型 → 本机网关”配置模型或聚合池，然后用同一个调用名称选择模型。
- “模型目录”分为已接入模型、聚合模型、上游目录。上游目录中的 ID 未接入前不能作为网关调用名称。
- 用户新建会话时选择 Roami，可选择网关模型，按标准能力筛选，并开启“仅免费”。界面不替换被筛选隐藏的已选模型。
- 原生会话里的模型选择独立保存；更换它不会修改节点主智能体、执行智能体的默认设置。运行中的原生任务不能切换模型。
- 主智能体与执行智能体的默认设置仍在“能力 → 智能体 → Roami”中统一配置。首页原有模型控件继续管理默认设置；本轮没有把它改成会话控件。

## CLI

```bash
# 默认读取已配置模型和缓存中的能力，不逐次联网探测。
roami model list
roami model list --json
roami model list --capability image

# 显式刷新上游声明，包含尚未接入的模型。
roami model list --refresh --all --json

# 已确认免费的单模型，以及保存了“仅免费”策略的聚合池。
roami model list --free

# 对话的模型选择只影响这个对话。
roami agent new --title 资料整理 --model free-pool --free-only --key research-chat

# 创建有持久会话记录的原生任务；不启动外部终端 Agent。
roami session new 资料整理 --kind roami --model free-pool --free-only \
  --task "整理本机资料" --dir /absolute/path --key research-task --json
```

`free-pool` 是用户保存的示例调用名称，程序不会自动创建这个池，也不会把模型名称的 `free` 后缀当作费用证明。`-model` 与 `--model` 都可用于原生会话创建。`--kind roami` 必须提供任务；结果包括 `roami:` 会话 ID、任务 ID、原生对话 ID。通过 Web 会话入口或 `roami agent history --conversation ID` 查看原生对话；它不是一个可用 tmux attach 的终端。

省略 `--model` 时沿用角色默认设置；显式 `--model auto` 使用已经绑定到网关的角色模型或聚合池。Auto 不会扩展池成员，也不会扫描整个上游目录。外部执行器原有 `agent execution launch` JSON 中的 `model` 字段保持现有语义。

## 能力与免费口径

- 模型条目有独立的 `kind`、`configured`、`enabled`、`protocol`、`pricing` 与 `capabilities`。
- 标准能力包括文本、图片输入、音频输入、视频输入、工具调用、推理、结构化输出、流式输出；保留未知状态。
- 能力按名称映射到 `{support, evidence, delivery}`。上游声明只标为 `advertised`；没有原生或适配证据时，`delivery` 为 `unknown`。本轮不新增伪造的“已验证”标签。
- 结构化输出只认 `structured_outputs` 声明，不把 `response_format` 参数等同于 JSON Schema。
- 聚合池不把成员能力的并集标成整个池的保证；因此未知能力的池不会出现在“图片支持”结果中。本轮的能力筛选用于选择，不是新增一套请求约束调度器。
- `advertised-zero` 只说明上游声明输入、输出 token 标价为零。`confirmed-free` 来自网关已有的已确认免费计价规则；`free-only` 表示聚合池的路由策略，不代表此刻必有可用成员。
- `--free-only` 对本次选择的请求强制执行，包含嵌套池；显式请求此约束时不会放行付费套餐额度。费用未知、无可用成员时失败，交给既有任务恢复流程；不悄悄放宽条件。
- 节点独立的记忆整理、通知、压缩等后台工作继续使用其保存的角色设置。单个会话选择免费模型不等于整个节点所有后台调用都免费；要让这些工作也使用免费模型，应配置对应的默认角色。未来的持续在线等待与恢复调度仍按统一设计迭代。

## 技术设计与代码

| 层 | 位置 | 职责 |
|---|---|---|
| CLI | `cmd/roami/model.go` | `model list` 的表格与 JSON 输出、能力与免费筛选 |
| 原生会话入口 | `cmd/roami/native-session-new.go` | 启动前验证模型、幂等创建原生任务并返回真实身份 |
| Go 网关目录 | `internal/modelgateway/model-directory.go` | 配置与缓存证据的统一目录；按来源、凭据和协议区分证据 |
| Go 请求选模 | `internal/modelgateway/model-selection.go` | 验证角色绑定和目录版本，路由本次请求并执行免费限制 |
| 运行时 | `providers/model_selection.py`、`core/loop.py` | 持久化每个对话选择，按 turn 构建独立 provider，用后关闭 |
| 存储 | `0029_conversation_models.sql` | 增量建立会话选模表；Go 备份恢复同步支持 schema 29 |
| Web | `ModelSelectionFields.tsx`、`NewSessionModal.tsx`、`useConversationModels.ts` | 新建 Roami 会话、标准能力筛选和原生会话独立选模 |

管理接口：`GET /v1/model-gateway/models`、`GET /v1/model-gateway/models/selection`、`POST /v1/native-sessions`、`GET/PUT /v1/conversations/{cid}/model`。Web 路由经现有鉴权代理暴露；CLI 使用节点私有 Unix socket。

目录默认只读缓存；上游声明缓存绑定完整来源指纹并在 15 分钟后失效，重启后按需刷新。显式刷新最多四个来源并发，整次限时 20 秒，逐源报告失败。刷新不会调用推理。并发请求各自携带选择、目录版本与角色路由身份，Go 在实际准入时重新核对；没有修改进程全局模型，也没有在 Python 增设额度规则。

原生会话的生成参数仍继承角色设置；本轮未新增每个会话的思考强度覆盖。模型能力实测、原生/适配证明和请求级多模态条件路由为后续实现范围。

## 验收记录

实际运行与截图记录见 [runtime-acceptance.md](runtime-acceptance.md)。原型和技术 HTML 继续作为设计参考，不把静态原型中的交互当作生产功能验收。
