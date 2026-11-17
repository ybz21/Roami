# Main 工作中切换模型

## 产品设计

首页和项目 Main 继续使用输入框已有的模型选择器。正在生成回复、执行工具或等待后台任务时，可以选择新模型及思考强度；当前请求继续完成，从下一次模型请求开始使用新配置。同一轮里，工具调用完成后也会重新选择模型，不必另开对话。

沿用节点级配置范围：该节点的所有 Main 共用选择，选择器中说明此范围及生效时机。不会切换专业执行器自身的模型，也不会重启已派发任务。连接、凭据及 worker 等整套配置变更仍需等待空闲；这些设置继续使用原有配置页。

命令补全及 `/help` 注册 `/model`：不带参数打开同一个模型选择器，`/model <模型ID>` 直接切换已配置连接上的模型，并重置思考强度。命令通过会话归属及本地配置权限检查，不写入用户消息、不创建轮次、不触发抢占。手工模型 ID 沿用现有配置的校验方式，实际可用性由网关及上游决定。

## 用户故事

- Main 正在读取代码时，用户选择另一个模型；读取结果只记录一次，原任务和对话继续，新模型完成接下来的推理。
- Main 正在流式回复时，用户调整模型；当前文字不中断，后续请求使用新模型。
- 用户在手机输入 `/model` 后选择模型，返回原对话；已有草稿和会话保持不变。
- 用户在另一个浏览器修改模型，已打开的 Main 通过事件更新模型标签，无需新增轮询。
- 网络重试重复提交同一个 `/model` 请求时返回原回执，不会覆盖之后的新选择。

## 技术设计

### 配置与发布

复用 Go 已注册的 `PUT /api/agent/model-settings` → Python `PUT /v1/model-settings`。`ModelSettings.save` 在原有互斥锁内区分主模型选择和整套配置：仅 main 的 model、reasoningEffort、images、contextWindow 可工作中发布，不重建或关闭 worker。验证、容量解析、候选 provider 构造成功后，沿用私有文件写入、fsync 和原子替换；发布成功后更新内存配置并发送 `model.changed`。

`providers/live_model.py` 提供稳定的 Main 句柄。每次请求/上下文阶段获取 provider 快照租约；切换退休旧 provider，已有租约释放后关闭旧连接。外部注入的初始 provider 保持原生命周期归属，运行时自行创建的 provider 由该句柄回收。

`core/loop.py` 在工具批次之间重新获取快照并重建上下文，保留 turn、branch、已持久化工具结果与任务。每个 prompt manifest 记录实际选中的模型、provider key 和设置 hash。

### 网关准入竞态

配置文件更新可能早于旧快照请求到达网关。只有可信 `ModelAdmissionRejected(MODEL_GATEWAY_ROUTE_CHANGED)` 且快照确实已更新时，Main 才丢弃未准入的空消息，重新选择模型并构建上下文继续。同一个 turn 内递增 manifest attempt，保留拒绝记录。普通传输异常、未知结果及其他准入错误不自动重放。压缩及回复审查等直接使用稳定句柄的消费者，也仅在未输出内容且确认旧路由未准入时重新选择 provider。

`TurnJournal.discard_request` 软删除未准入的空消息并发送 `message.discarded`；前端只撤去该消息，保持轮次运行状态。已开始的流不取消；网关配额、计费及路由校验仍由 Go 网关负责。

### 命令与交互

- `protocol/commands.py`：注册 `/model` 及可选参数。
- `conversation/model_commands.py`：沿用 requests/jobs 记录及 requestKey 冲突检查，保存成功回执，串行处理命令重试。
- `AgentConversation` → `AgentComposerPlus` → `AgentModelPicker`：通过打开请求调用现有选择器；等待发送状态解除后打开，不重复打开。
- `useAgentThread`：收到 `model.changed` 复用 `MODEL_SETTINGS_CHANGED` 刷新；不增加轮询。
- 中英文语言包同步说明切换范围、生效时机和结果。

## 验收

回归与浏览器证据见 [acceptance.md](acceptance.md)。未修改用户正在运行的实例、真实模型路由或会话数据；验证使用隔离实例和可控模型夹具。
