# 后台任务 failed / interrupted 根因排查与修复

排查基线：`08ad956b`；日期：2026-11-02；项目：`2026-0728-1202-30xe`；仓库：[ybz21/Roami](https://github.com/ybz21/Roami)。

## 结论与范围

这批失败并非同一个根因。最大历史类别是旧执行步数限制（8 次），其次是无法区分 deadline 与中断的旧混合码（5 次）。当前代码仍有 7 个可复现缺陷，本次分别建 issue 并修复：停止判定、异常原因链、CLI 中断分类、项目错误透传、native 目标准入；截图补充的 unknown 生命周期取消围栏、观测原因丢失。**2 次历史 NATIVE_WORKSPACE_OUTCOME_UNKNOWN 的内层事件与工具记录确有 TOOL_OUTCOME_UNKNOWN，不能认定它们属于“已停止异常被误判”的新发现缺陷。**

本次只读生产 SQLite，不修改生产任务、凭据、模型路线、浏览器配置或工作区；没有重放未知写入，也未部署或合并。现有 issue #350、#398 的完整验收不在本次修复范围内。

## 数据口径与频次

快照时间：2026-11-02T10:28:00.402402+00:00。数据通过 SQLite `mode=ro` 只读查询读取节点当前登记的 `agents/runtime.db`（含 WAL 可见数据），范围 2026-10-18 至 2026-11-02；53 个任务、77 次尝试。任务状态：20 failed、5 interrupted、18 succeeded、8 waiting_user、1 cancelled、1 running。尝试中 28 failed、5 unknown；**其中 1 个 unknown 没有 result，所属任务仍 running，不能计为已中断。** “other/no summary”的 failed 记录也不能从 attempt.state 单独推断任务状态。

下表按历史 attempt 累计，包含旧 revision 和后来续作成功的任务，不能拿它直接当当前失败任务数。project 列只统计 intent.target.projectId 或已绑定 target_json.projectId 精确匹配目标项目的记录；目标是 session、散目录或仅正文提及项目的记录不会被猜测归入该项目。project 列共有 14 个 failed/unknown 历史尝试，其中 1 个仍在观测。当前任务本身未纳入错误码归因。

| summary / errorCode | attempt.state | 节点次数 | 精确项目次数 |
| --- | --- | ---: | ---: |
| `(other/no summary)` | failed | 1 | 0 |
| `(other/no summary)` | unknown | 1 | 1 |
| `AGENT_STEP_LIMIT` | failed | 8 | 6 |
| `BROWSER_DRIVER_UNAVAILABLE` | failed | 2 | 0 |
| `CODING_SESSION_TARGET_CONFLICT` | failed | 1 | 1 |
| `EXECUTION_DEADLINE_OR_INTERRUPTION` | failed | 5 | 4 |
| `EXECUTION_FAILED` | failed | 1 | 0 |
| `MODEL_DEADLINE` | failed | 1 | 0 |
| `MODEL_HTTP_401` | failed | 1 | 0 |
| `NATIVE_TARGET_ADAPTER_NOT_IMPLEMENTED` | failed | 1 | 0 |
| `NATIVE_WORKSPACE_OUTCOME_UNKNOWN` | unknown | 2 | 0 |
| `NATIVE_WORKSPACE_UNAVAILABLE` | failed | 1 | 0 |
| `PROJECT_PROVISION_UNAVAILABLE` | failed | 1 | 0 |
| `SESSION_LIFECYCLE_UNAVAILABLE` | failed | 2 | 1 |
| `SESSION_NOT_IDLE` | failed | 1 | 0 |
| `TOOL_ARGUMENT_REPAIR_STALLED` | failed | 1 | 0 |
| `TOOL_OUTCOME_UNKNOWN` | unknown | 2 | 0 |
| `WORKSPACE_STALE` | failed | 1 | 1 |

[机器可读频次和脱敏 attempt 标识](frequency.json) 保存捕获时间与逐条证据；没有导出任务正文、模型 key、工具参数、原始异常文本。统计使用 `result.errorCode` 优先，否则使用全大写且无空格的 summary；自然语言或缺失结果归入 other/no summary。所有请求或模型轮次的错误数量不等于任务频次，本表没有把日志中重复报错累加为多次任务。

复核 SQL：

```sql
BEGIN;
SELECT state, count(*) FROM tasks GROUP BY state;
SELECT a.state, json_extract(a.result_json,'$.summary'), count(*)
FROM task_attempts a
GROUP BY a.state, json_extract(a.result_json,'$.summary');
COMMIT;
```

## 根因聚类与代码证据

以下 file:line 为修复后当前文件位置，issue 正文另记了排查基线位置；频次表示相关错误码出现次数，**不等于已证明由某一新 bug 导致的次数**。

| 根因与分类 | 频次及触发条件 | 代码位置与判断 | 跟踪 |
| --- | --- | --- | --- |
| 旧硬步数限制；历史代码/预算策略 | AGENT_STEP_LIMIT 8（项目 6）；旧长工具链达到限制 | 当前 `core/loop.py` 不再产生此码；`server/configuration.py:195` 的兼容字段 max_steps=0；`test_unlimited_execution.py:11` 验证即使 max_steps=1 仍能完成 20 次工具调用。未重跑历史任务 | [已有 #350](https://github.com/ybz21/Roami/issues/350)，不重复建 issue |
| CLI deadline/中断混用；可观测性缺陷 | EXECUTION_DEADLINE_OR_INTERRUPTION 5（项目 4） | `internal/agentexecution/execution.go:453,491` 与 `structured-process.go:126`。旧代码把 context deadline 和 cancel 同码；不能从历史 summary 推断原因 | [#590](https://github.com/ybz21/Roami/issues/590)，本次修复 |
| 工作区异常停止判断短路；状态机缺陷 | 可受影响的历史 summary 2，但历史两次均有真实 unknown 工具，**确证误判历史数量未知** | `executors/workspace.py:94-109`：旧 BaseException 设置 confirmed=False，`confirmed and await stopped()` 永不读取停止证据；OSError/ValueError 且 stopped=True 可复现误判。保留明确 unknown 副作用 | [#592](https://github.com/ybz21/Roami/issues/592)，本次修复 |
| 异常类型/内因丢失；可观测性缺陷 | EXECUTION_FAILED 1；工作区包裹码 2 | `dispatch/runner.py:19-42,251`：旧通用异常仅写 EXECUTION_FAILED。历史通用异常 turn.failed=MODEL_ERROR，但没有异常类，不能声称是 120 秒模型超时。新结果保留类型与安全 causeCodes | [#591](https://github.com/ybz21/Roami/issues/591)，本次修复 |
| 项目 CLI 错误被前缀过滤；代码缺陷 | PROJECT_PROVISION_UNAVAILABLE 1，具体旧 CLI 原码未知 | `executors/project.py:39-48`：旧实现只保留 PROJECT_ 前缀。实际 CLI 可能返回 INVALID_PROJECT_PROVISION（`backend/project/provision.go:73`）或 CLI_ERROR（`cmd/roami/api-command.go:178`），旧前缀过滤会丢弃；测试还覆盖 REMOTE_REQUIRED/AUTH_REQUIRED 等合法码；修复保留合法公开码，非法消息继续拒绝 | [#593](https://github.com/ybz21/Roami/issues/593)，本次修复 |
| 不支持的 native session 先接受再失败；准入缺陷 | NATIVE_TARGET_ADAPTER_NOT_IMPLEMENTED 1；历史 target.kind=session，无工具启动 | `dispatch/tasks.py:104-107` 与 `executors/workspace.py:48`。Main 路由 `dispatch/routing.py:179` 的已有会话发送与 Tasks.create 接口不同；应在后者提前拒绝 | [#594](https://github.com/ybz21/Roami/issues/594)，本次修复 |
| 会话正在运行；调度时序/外部状态 | SESSION_NOT_IDLE 1 | `internal/agentexecution/session-lifecycle.go:345-348`、`persistent-session.go:134-137` 检查生命周期状态、工具和进程；`dispatch/runner.py:242,280` 当前已按 launch key 退避排队；`executors/roami_cli.py:166` 只对发送前明确拒绝重试，未知发送不重放 | 当前已修，212 项定向验证含会话重试；不重复建 issue |
| 旧会话缺生命周期回调；环境/兼容前置条件 | SESSION_LIFECYCLE_UNAVAILABLE 2（项目 1） | `internal/agentexecution/session-lifecycle.go:342`、`persistent-session.go:111` 无 binding 时拒绝跟踪；防止猜测 TUI 完成。需要接入回调的会话或原消息追加流程 | 非新代码 bug；已有设计验收 `docs/design/20261018-agent委派验收/README.md` |
| 工作区被删、变路径或 Git 归属不符；安全前置条件 | WORKSPACE_STALE 1（项目 1） | `internal/agentexecution/workspace-registry.go:80-123` 验证规范路径、ID、commonDir、worktree；不能自动 reset 或换目录覆盖用户工作。历史没有原路径判定细节 | 当前保留拒绝；需人工核对原工作区 |
| 工作区启动/CLI 传输不可用；环境或历史可观测性缺陷 | NATIVE_WORKSPACE_UNAVAILABLE 1，尚未开始工具 | `executors/workspace.py:69-87` 在 EOF、非 JSON、结构不符时产生；Go 已通过 `internal/agentexecution/native-workspace.go:45-54` 发结构化准备错误。`test_task_target_admission.py` 覆盖 WORKSPACE_STALE 穿透 | 未知具体环境原因；本次 #591 留原因类型，未伪造旧日志细节 |
| 模型凭据/网络响应；外部前置条件 | MODEL_HTTP_401 1、MODEL_DEADLINE 1 | `providers/chat_completions.py:178,261`、`providers/model_proxy.py:228` 产生。401 是上游认证拒绝；deadline 可能显式模型等待预算或上游迟迟不返回。当前默认不限与显式配置均需按节点配置判断 | 不修改凭据/模型路由、不用替代模型掩盖；参考已有 #350 |
| 真实未知工具副作用；保护状态，不等于代码错误 | TOOL_OUTCOME_UNKNOWN 2；另有 2 次被 NATIVE_WORKSPACE_OUTCOME_UNKNOWN 包裹 | `tools/gateway.py:646`、`executors/native.py:89`、`storage/workspace_files.py:211` 等在未获确定结果时产生；`dispatch/runner.py:267-276` 写 outcomeKnown=False、retryable=False、interrupted。历史包裹两次分别有 browser_open unknown 和 browser_act unknown（后者也有已成功 bash） | [已有 #398](https://github.com/ybz21/Roami/issues/398)，本次保留保护并改进原因链 |
| 反复相同工具参数且无进展；明确失败保护 | TOOL_ARGUMENT_REPAIR_STALLED 1 | `core/loop.py:379`；`test_argument_repair_progress.py` 验证同参同问题停滞终止、改参/成功工具继续。旧底层参数契约缺陷已有 [#397](https://github.com/ybz21/Roami/issues/397)、[#359](https://github.com/ybz21/Roami/issues/359) | 不删除保护、不重复建 issue |
| 浏览器驱动不可用；环境/依赖前置条件 | BROWSER_DRIVER_UNAVAILABLE 2 | `executors/browser_driver.py:234,351` 检查驱动依赖。当前 `roami chrome capabilities` 实测可读到 browserId 与 operation_receipts/scene_observation 能力，**只证明现在连接可用，不代表历史驱动存在或网页动作通过** | 已有 [#402](https://github.com/ybz21/Roami/issues/402)、[#407](https://github.com/ybz21/Roami/issues/407)；本次不重启浏览器 |
| session 与目录覆盖冲突；正确参数拒绝 | CODING_SESSION_TARGET_CONFLICT 1（项目 1） | `dispatch/tasks.py:134-139` 和 CLI spec 不允许指定已有 session 又覆盖 directory/workspace/base/remote，避免写错目录 | 非新缺陷；应保留原会话目标 |
| 自然语言/缺失结果；不可直接归因 | failed 1、unknown 1 | 自然语言失败尝试所属任务 interrupted；另一个 unknown attempt 属仍 running 的任务，result 为空 | 不计入上述错误码根因；未据此改状态 |

## 新增截图：执行待确认与正在停止

用户在本次执行中追加的截图已单独只读取证，未重写初始频次快照。当前任务（`f169ed78…`）初始是 running / attempt unknown、result 为空；随后已有 task_steer 要求补充排查，`TaskRevisions.request` 发起 cancellation，于是 task=cancelling、queued steer=1，执行器仍在工作。Go Status 返回 unknown、lifecycle=unknown、pending tools=1、cancel.json 存在、result.json 不存在。[脱敏现场快照](live-session-observation.json)。

- **显示条件**：`frontend/src/components/agent/AgentTasks.tsx:100-104,154` 在 task 为 running/preparing 且最新 attempt.state=unknown 时显示“执行待确认”；`dispatch/tasks.py:494-503` 对 unknown 且无 result 默认 outcomeKnown=false、stopConfirmed=false。这是观测不确定，不证明执行器退出、任务完成或已经停止。task=cancelling 显示“正在停止”，只代表取消意图。
- **确定代码缺陷 [#595](https://github.com/ybz21/Roami/issues/595)**：原 `session-lifecycle.go` 的取消检查还要求 lifecycle=busy；unknown 以后，即使 cancel.json 已存在，同 provider/turn/launch 的新 PreToolUse 也绕过围栏。现在移除该额外 busy 条件，保留 provider/turn/launch 身份校验与未停止保护；不清空 pending tools，不伪造终态。
- **观测缺陷 [#596](https://github.com/ybz21/Roami/issues/596)**：原所有 unknown 分支没有原因。现在持久化首个 unknownReason（例如 provider 改变、prompt/工具回调不匹配、停止未确认）；Status 返回 observationErrorCode，区分身份不可观测、缺 lifecycle、launch 不匹配、明确 deadline、hook 不确定。Python 在既有 observation_unknown 事件和 task.latestAttempt 中保留公开码；同原因不重复刷事件，原因改变及恢复仍有记录。
- **未证实部分**：现场旧 lifecycle 没保存 unknownReason，也无原始 hook 事件日志，因此无法确定首次 unknown 是哪个具体回调造成。代码中会把错 turn、缺 ToolID、prompt 不匹配等都转 unknown；没有把其中任何一种猜测写成现场定论。本次新增诊断从部署后才开始留证。
- **当前任务限制**：未把新二进制部署到正在执行的任务，未改 cancel.json 或生产 SQLite，未推进其 revision。截图中的运行实例可能仍在“正在停止”，不能宣称界面已恢复。

## 已实施修复

1. **停止判定（#592）**：对普通异常读取真实 stopped()，有肯定证据才释放租约并保留原异常；无回调或 stopped=False 仍 unknown。明确 TOOL/MCP unknown 即使 stopped=True 仍不转为已知。取消不被改成成功。
2. **安全诊断（#591）**：task attempt 结果增加 errorCode、failure.exceptionType、failure.causeCodes；原因链最多 8 层、去重、防环，仅允许公开错误码，不写原消息或 traceback。裸 TimeoutError 分类 EXECUTION_TIMEOUT，**不猜测是模型超时或任务 deadline**。验证后数据库结果仍保留这些字段，未知工作仍 interrupted。
3. **执行中断分类（#590）**：普通与 structured CLI 共用 context.Err 分类，返回 EXECUTION_DEADLINE / EXECUTION_INTERRUPTED；显式 cancel.json 仍 cancelled。部分 stdout/stderr 继续保存。
4. **项目错误透传（#593）**：接受符合 public_error_code 规则的结构化码；含私密文本、空值或非法格式仍回退通用码。
5. **目标准入（#594）**：不支持的 native session 在 Tasks.create 创建 task/attempt/job 前拒绝；不静默换目录或换执行器。
6. **unknown 下的取消围栏（#595）**：保持同一身份校验，取消意图在未知生命周期下同样禁止启动新工具，等待真实停止证据。
7. **观测错误追踪（#596）**：Go 持久化首个 unknownReason 并在 Status 回传 observationErrorCode；Python 校验公开码、记录原因变化并在 task 状态详情暴露，恢复后不残留错误码。

[设计与架构记录](../../design/20261102-task-failure-diagnosis/README.md)。新增值是技术错误码/执行记录字段，未新增 UI 文案或改界面；不适用手机视觉/触屏验收。

## 验证证据

- 新增反例通过只读替换模块源码在基线 `08ad956b` 上执行：Python 13 failed / 12 passed（多组参数覆盖同一根因，不是 13 个独立 bug）；Go overlay 的普通 deadline、父 context 中断与 structured 两种分支均按预期失败。[原始输出摘录](baseline-verification.txt)。未切换工作区或运行历史任务。
- 修复后首轮定向 52 passed / 12.24s；追加准入、会话排队、超旧步数工具链、参数修复进展和 native 未知恢复 212 passed / 48.99s。Go deadline/父中断/structured/取消定向回归通过。
- 最终受影响路径定向回归：286 passed / 64.42s；Go deadline/中断/取消/观测回归通过（3.029s）。[命令输出](verification.txt)。截图新增的 unknown 取消围栏在基线 Codex 与 Claude 两分支均返回 nil（未拦截），缺生命周期、错 launch、deadline、身份不可读四个观测分支均没有原因码；相同反例修复后通过。
- 首次全仓 quick 被未改动的 `backend/config/TestBridgeEnvAliases` 挡住：继承 ROAM_HOME 与测试自设 ROAMI_HOME 不一致。测试命令只对自身进程 `env -u ROAM_HOME`，未改任何节点配置或测试实现。重跑已通过：提交钩子 quick 的 Python 3059 passed / 48 skipped（797.70s）；初次 quick 为 3054 passed / 48 skipped（截图新增用例尚未加入）。
- 最终完整门禁 `env -u ROAM_HOME bash scripts/dev/quality/check.sh full` **通过**：Go 全仓测试，Python **3059 passed / 48 skipped**（796.57s），ruff lint/format、i18n 4763 keys、hover、typecheck、Vite build（42.88s）和压缩产物、秘密扫描与文件策略均通过。
- 最终提交钩子执行 `quick` **通过**，Python 3059 passed / 48 skipped（797.70s）。没有跳过钩子；按仓库规则先安装了 tracked hooks。48 个跳过项保持 pytest 原有的外部环境/集成 opt-in 条件，不把它们算作成功验收。
- 文档链接与频次汇总已校验；未改 frontend/src，不适用新增手机 UI/触控验收。截图是实际日志查看页，经 `roami chrome screenshot --fresh` 捕获，不是生成的测试结果图。源码差异、测试通过与发布到生产是不同阶段，本次没有生产独立验收。

## Issue、PR 与未完成项

- [execution-deadline](https://github.com/ybz21/Roami/issues/590)：已建立并在本分支修复。
- [failure-context](https://github.com/ybz21/Roami/issues/591)：已建立并在本分支修复。
- [native-stop](https://github.com/ybz21/Roami/issues/592)：已建立并在本分支修复。
- [project-code](https://github.com/ybz21/Roami/issues/593)：已建立并在本分支修复。
- [native-admission](https://github.com/ybz21/Roami/issues/594)：已建立并在本分支修复。

- [session-unknown-cancellation](https://github.com/ybz21/Roami/issues/595)：已建立并在本分支修复。

- [session-observation](https://github.com/ybz21/Roami/issues/596)：已建立并在本分支修复。

[回归日志截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-597/regression.png)（只存 pr-shots 分支，未提交到 main）。

运行时修复提交：`508abe62`；分支：`agent/a731ff893788cf273fba8922`。

PR：[draft #597](https://github.com/ybz21/Roami/pull/597)。本分支修复均未合并、未部署，因此历史数据不变，不能宣称线上失败率已经下降。PR 已确认 draft / OPEN / MERGEABLE；GitHub CI 仍在运行，本地门禁通过不代替 CI 结论。

剩余事项：

- #350 的真实模型历史对话全量重跑、上线配置审计与部署验收仍待原 issue 完成；本次不改变节点保存的模型路线或参数。
- #398 的旧未知恢复仍需逐任务停止与副作用核验。`dispatch/tasks.py:497-503` 的 stopConfirmed 派生仍要求 outcomeKnown 非 false，因此“inputStopped=true 但最终结果未知”的旧任务也会回报 stopConfirmed=false；此字段的语义拆分仍需与恢复/重放契约一起审计，未在本次局部放开。当前 stopped_navigation 只支持 resourceOnly 的纯导航且有明确停止证据；两个 project 工作区未知任务不能被无条件套入这个恢复入口。
- 工作区 lease 的 Go deadline 与 Python 最终释放确认可能发生竞态；本次只修正已观察的分类路径，没有为原 hold 协议设计新的停止宽限/接管协议。必须继续保持 unknown，不能因 deadline 到期便声称工具已停。
- 凭据失效、旧 session 无回调、工作区实际失效、当时浏览器驱动不可用均未替用户更改环境；旧通用错误缺证据，无法恢复未保存的原诊断。
- 平台 capability read 返回 ACTIVE_TASK_CONTEXT_REQUIRED；使用仓库同源 Roami Skill 与本机只读数据库完成调查，未读取或复制私有 context 内容。

没有声称通过线上独立验收；没有修改无关文件、关闭用户会话、合并 PR 或重新执行历史未知操作。
