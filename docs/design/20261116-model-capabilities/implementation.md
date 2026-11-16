# CLI 与 Roami 创建会话选模

本轮保留模型能力目录、`roami model list`、Web / CLI 创建 Roami 会话时指定模型和仅免费约束。网关工作区复用本机网关会话的生产实现（`5f99951a`）；另一个会话的工作区不变。

## 产品行为与用户故事

- 用户在本机网关配置模型或聚合池，然后以相同调用名称创建 Roami 会话。
- 创建界面按模型类型、标准能力和免费条件筛选；筛选不替换已经选定的模型。
- 选定模型保存到原有任务的 `intent_json.model`；仅免费保存为 `intent_json.freeOnly`，恢复任务时一并读取。
- 省略模型或选择 `auto` 时，沿用执行角色保存的默认模型或池。显式模型只影响这个任务。
- 不新增已有会话切模功能；默认模型继续在“能力 → 智能体 → Roami”中配置。

## CLI

```bash
roami model list
roami model list --json
roami model list --capability image
roami model list --refresh --all --json
roami model list --free

roami session new 资料整理 --kind roami --model free-pool --free-only \
  --task "整理本机资料" --dir /absolute/path --key research-task --json

roami session new 调研 --kind roami -model auto --task "整理资料"
```

`free-pool` 是用户保存的示例调用名称，不会自动创建。`-model` 与 `--model` 都受支持。结果包括 `roami:` 会话 ID、任务 ID、原生对话 ID；通过 Web 会话入口或 `roami agent history --conversation ID` 查看，不使用 tmux attach。

`roami agent new` 保持原有命令接口。受管智能体通过已有注册任务能力传入 `model`；新增用户 CLI 入口保留受管上下文限制。

## Agent 动态选模与委派

首页模型选择器继续使用原有网关目录：列表和当前选中项显示模型名称与“原生 / 聚合”，缺失目录时保留“类型未知”。“原生”表示单模型入口，不代表输入能力已经做过原生/适配实测。打开列表会刷新现有目录，类型和模型增删跟随节点配置，不在 Agent 代码维护固定模型名单。

Agent 可以通过 `roami model list --json` 查询当前模型或池 ID，然后在原有委派工具中传入：

```json
{"goal":"整理资料","executor":"native","model":"free-pool","freeOnly":true}
```

`model`、`freeOnly` 是 `delegate` 的可选参数；不传时沿用默认设置。它们进入同一个任务 intent，并由原生执行器、Provider 和 Go 网关执行。已有会话的执行器与工作区绑定继续保持，不能用这些参数绕过续接契约。

目录配置更新在后续调用生效，不需要修改 Agent 代码或重启。模型已删除、上游引用失效时显示“当前模型不可用，请在模型列表中重新选择”，不只显示通用重试提示。

## 技术设计

复用现有链路：

```text
创建会话 / 任务 → task.intent_json → NativeExecutor → AgentLoop
             → 现有 ChatCompletions（覆盖 model）→ Go 网关现有目录路由
```

- 不新增选模服务、选模预校验接口、专用请求头、目录版本握手或数据库迁移。
- NativeExecutor 从任务记录读取模型，随现有 turn 传入；AgentLoop 在有覆盖时使用 Provider 的浅拷贝，共享原有 HTTP 连接，互不改写模型、参数与缓存身份。
- Provider 使用原有请求体的 `model`；仅免费以 `roami_free_only` 布尔字段传给本机网关。Go 在转发上游前移除此字段，使用现有计价与聚合路由执行约束。
- 默认角色配置、生成参数与原有路由身份校验继续有效。选模不修改进程全局模型，也不在 Python 增设费用规则。
- 模型是否存在、启用、可用，以及免费路线是否满足条件，在实际调用时由 Go 统一判断。不存在的模型可形成任务记录，但执行失败，不调用上游。

| 位置 | 增量职责 |
|---|---|
| `cmd/roami/model.go` | 模型目录表格、JSON、能力与免费筛选 |
| `cmd/roami/native-session-new.go` | 幂等创建原生任务、返回真实会话身份 |
| `internal/modelgateway/model-directory.go` | 配置与上游声明缓存的统一能力目录 |
| `internal/modelgateway/handler.go`、`catalog_http.go` | 用请求中的模型走既有目录路由、执行仅免费约束 |
| `executors/native.py`、`core/loop.py`、`providers/chat_completions.py` | 从现有任务传递模型，复用 Provider 连接 |
| `dispatch/tasks.py`、`protocol/http.py`、`server/http.py` | 创建入口与原有任务字段透传 |
| `tools/main_catalog.py`、`tools/model_inputs.py` | 原有 delegate 工具暴露、传递模型与免费条件 |
| `useAgentModels.ts`、`AgentModelPicker.tsx` | 动态目录、原生/聚合标识与原有默认模型切换 |
| `ModelSelectionFields.tsx`、`NewSessionModal.tsx` | 新建会话选模与能力筛选 |

新增管理接口仅有模型目录查询 `GET /v1/model-gateway/models` 和原生会话创建 `POST /v1/native-sessions`。不增加会话模型 GET/PUT 接口。

## 能力与免费口径

标准能力包括文本、图片、音频、视频、工具、推理、结构化输出和流式输出。缺失证据保留未知；上游声明标为 advertised，不冒充验证或原生支持。聚合能力不取成员并集。

`advertised-zero` 只代表 token 标价声明；`confirmed-free` 来自网关已确认计价规则；`free-only` 代表池策略。仅免费包含嵌套池，不放行付费套餐额度；无免费成员或费用未知时失败，不回退到付费。定价在准入中改变时拒绝旧的免费决策。

节点独立的记忆、通知、压缩任务仍使用各自的角色设置；单任务免费不保证整个节点零费用。请求级多模态条件路由、能力实测和长时等待恢复仍是后续范围。

## 验收

当前修订见 [简化验收](simplification-acceptance.md)。此前 [运行验收](runtime-acceptance.md) 保留原始历史证据，其中已撤回的会话切模功能不代表当前交付。
