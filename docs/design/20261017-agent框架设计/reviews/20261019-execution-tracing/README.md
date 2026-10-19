# 执行链追踪与主对话调度（2026-10-19）

跟踪：[Issue #330](https://github.com/ybz21/Roami/issues/330)。此目录记录实现与实测，不修改已批准架构。原有依据是 technical/08-operations.html 的“观测与成本”。

## 调研结论

| 项目 | 已核对的机制 | Roami 借鉴点 |
| --- | --- | --- |
| Pi 最新 upstream main | `pi-telemetry` 提供显式父子 Context/Span、跨进程 carrier、链接、指标和适配器合约；不绑定 exporter/backend。参考内存适配器没有时间戳，不能直接当性能分析器。 | 保留领域 ID 和父子/因果关系；诊断失败不能改变业务结果；默认不记录消息内容与凭据。 |
| OpenClaw | `diagnostics-otel` 将内部诊断事件导出为 OTLP/HTTP traces、metrics、logs；区分真实 provider request 与不透明 CLI turn。 | 外部 Codex/Claude 只记录实际可见边界，内部调用、未知 Token 不能编造。 |
| LangSmith | 提供 Agent 可观测后端及 OpenTelemetry 接入。 | 如后续需要集中检索和趋势图，可选择兼容后端；本轮没有部署或接入。 |

核对的 Pi main commit：`1402973a9dbe8c627341e04c9744c54953e285ca`。链接：

- [Pi telemetry README](https://github.com/earendil-works/pi/blob/1402973a9dbe8c627341e04c9744c54953e285ca/packages/telemetry/README.md)
- [OpenClaw OTel](https://docs.openclaw.ai/gateway/opentelemetry)
- [OpenClaw model observation units](https://docs.openclaw.ai/gateway/opentelemetry/model-calls-and-metrics)
- [LangSmith observability](https://www.langchain.com/langsmith/observability)
- [GLM 官方推理强度说明](https://huggingface.co/zai-org/GLM-5.3-Flash#note)：支持 low / high / max，不设置默认 max；低强度不等于关闭推理。

## 本轮实现

- 查询：`roami agent trace --turn TURN_ID`，或 `--task TASK_ID`。从 Worker 或回报 turn 查询也向上找到同一根链路。
- 时间线导出：`roami agent trace --turn TURN_ID --format chrome > trace.json`，可由本地 Perfetto / Chrome trace-event 查看器导入。默认 JSON 保留 Roami 标准 data envelope；chrome 格式剥离 envelope。
- HTTP：Go 原有鉴权下的 `GET /api/agent/traces?turnId=...`；私有 Python 路由 `/v1/traces`。turnId / taskId 必须二选一，按 owner 隔离。
- 覆盖：Python 接收/排队、上下文准备、Main/Worker 模型轮次、HTTP 重试和退避、响应头/首个非空增量/首段文字、工具、后台 run 和 Main 结果回报。模型信息记录在现有 manifest，工具/任务复用既有持久化事实；没有新增业务库和外部服务依赖。
- 历史数据仅从 message lifecycle 推断时注明 timingSource；缺失耗时或 Token 保留 null，未知状态保留 unknown。并发 Span 耗时之和可以超过用户等待时间，不能直接相加当总耗时。
- 只导出 ID、工具/模型名、时间、状态和标准化用量等元数据；不导出 Prompt、消息正文、工具参数/输出、凭据或文件内容。新增 timing 记录失败只记固定诊断，不触发模型重试。
- 这是本地 waterfall/JSON 查询与导出，不宣称已经接入 OpenTelemetry SDK 或 OTLP collector。当前起点是 Python turn admission、终点是 Main 回复落库；Go 入口、浏览器收到/绘制、后台记忆提取的独立模型请求以及专业 Agent 内部子步骤尚未独立埋点。

## 主对话行为

- 一条可见 Main、同一分支最多一个 running turn 的约束保留。
- 新用户意图到达时，若 Main 在等待模型，取消这次模型生成，将原 turn 和原 job 置回 queued。请求、原消息、已完成工具和后台任务保留，优先执行新意图，再恢复原意图。
- 工具运行中不自动强杀；一批工具回执完整落库后让出，恢复时消费已有回执。新请求不等于取消旧任务。
- 恢复使用同一 turn ID、递增模型 attempt，仍受原步骤上限限制。恢复上下文排除未来 turn，原对话来源和授权不替换为新问题。
- 全部 delegate 已取得持久化队列回执时，直接结束 Main 本轮，依靠任务卡说明已接收；不再调用一次模型重复确认。失败、非委派工具和需要后续动作的情况照常继续。
- 新用户输入优先于积压的任务回报/让出轮次；停止命令也覆盖尚未开始的排队 Main。本轮不改变 `/stop` 只停止当前 Main 回复、不默认取消所有后台任务的约定。
- 新增 recovery 提示：Main 无工作区时直接下放实际任务，避免反复猜 cwd、查项目、尝试 curl；明确当前请求边界，防止连续问题被合并委派。
- 让出的模型请求需要重新生成；被取消请求的未知用量不记为 0。连续输入可能增加模型请求成本。本轮没有承诺首段有效回答 P95 ≤2 秒已经达标。

## 实测记录

原有相同模型配置的历史证据：R03 总等待 205.729 秒、Main 派发轮 66.198 秒、Worker 110.251 秒、Main 回报 32.062 秒；R04 总等待 217.795 秒、Main 派发轮 119.194 秒、Worker 91.552 秒、回报 11.160 秒。各段有并行，不能相加代替总等待。

新追踪还观察到：上下文约 6ms；一次 provider 在约 3.9 秒出现首个增量，但无可展示文本，120 秒触发 MODEL_DEADLINE；另一轮约 4 秒开始返回增量、约 36 秒才出现正文。因此既要减少多余模型轮次，也要实测当前主模型的推理强度。

连续任务实测另复现浏览器队列故障：已经断开的 liveness probe 在串行队列轮到它时才安装收包监听，导致等待已丢失的 close/input 事件。修复为忽略已销毁连接；真实 TCP 回归测试证明后续命令不再被它卡住。

真实模型后续结果、配置差异、失败迭代及最终截图在同目录验证记录中补充；控制天气页面是隔离夹具，不是真实天气服务。不得将仅收到请求或只通过模拟测试写成真实完整链路已完成。


## 本轮最终验证

- `scripts/dev/quality/check.sh full`：Go 全库、Python 529 项、ruff、前端 typecheck/i18n/hover/build 与 secret scan 均通过。
- `node --test backend/browser/automation/*.test.mjs`：26 项通过，含断开探活连接不再阻塞队列。
- 最新请求上下文修正后，真实基础连续两问通过：第二问 0.030 秒接收，两个独立任务来源均回报随机新凭证，合计 40.75 秒；模型等待时停止为 0.153 秒。Main `glm-5.3-flash` / `reasoning_effort=low`，Worker `rr/gpt-6.1-sol` / 原参数 `{}`。
- 专用 tmux 接收器投递 D03、歧义选择 D05、实际压缩并继续 C03、自动记忆 M01、跨对话召回 M02 再次通过。
- 多 Skill 报告 R03 153.29 秒（HTTP 验收总时间），DB 链路 153.009 秒。对照同时变化代码与 Main 参数，不宣称单因素提升。该用例早于最后一次待处理请求上下文修正，后者另由连续提问验证。
- `--repeat-previous` 复杂追加仍未通过：重复派发和 Main 复述遗漏新凭证。`stress-failure.json` 保留实际状态，Issue #330 未关闭。只读查询误走工作区导致 waiting_user、2 秒首段有效回答目标、跨 Go/客户端及后台记忆独立埋点仍为后续工作。
- 桌面和 Android 真机均打开交互时间线，切换链路、展开工具与诊断信息，无文档横向溢出。截图通过 PR 的 pr-shots 孤儿分支提供，不进入 main。

- Android 真机在隔离 Main 中通过实际触控发送与停止；数据库确认该 turn 为 interrupted，输入框仍可继续使用。生产会话未发送测试消息。
