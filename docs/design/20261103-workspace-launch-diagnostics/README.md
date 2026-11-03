# 启动前工作区围栏拒绝的失败诊断

排查日期：2026-11-03；基线 `4b9341af`；[issue #639](https://github.com/ybz21/Roami/issues/639)。本报告的“执行器启动”专指接收任务并执行的供应商 CLI，和 tmux 内 Roami runner 启动区分。

## 结论与既有成果

样本 `65291b93a72e418d87f13c8d3cdc9585` 的失败点在 **Claude 任务 CLI exec 之前的 workspace_claim**。它无法取得目录写入资格：writer.json 仍指向旧执行 `163d773b30abb90c977481b8a32878d6d6238f2dd271a070d2c7bc9e7d67ec80`，其 result.json 缺失。新 runner 由 failPersistent 手工写入 failed / WORKSPACE_OUTCOME_UNKNOWN / exitCode=-1；**这里的 -1 不是已观测到的退出码、信号、参数错误或模型鉴权失败**。第一次任务工具调用根本没有发生，没有 Claude 工具 stderr 可补取。上游旧会话日志另有明确的 PostToolUse:Read / AGENT_INPUT_TOO_LARGE：工具结果过大导致旧 hook 回调在进入生命周期状态机前被拒绝（已有 #523 / PR #524 修复）。未恢复的旧 writer 继续阻塞新任务；本次新增修复是围栏拒绝原因和阻塞来源丢失，使用户将“未开始”误读为“开始后工具失败”。

已先读关联任务 `f169ed78c1614449a6f18d65b222a2c6` 的[排查报告](../../reviews/20261102-task-failures/README.md)、[续作报告](../../reviews/20261102-task-failures/followup-history.md)及设计记录，确认 [PR #597](https://github.com/ybz21/Roami/pull/597) 已合入。其 #591、#592 是 native 异常链和停止判定，#595、#596 是会话取消围栏与观测原因，均不能补回历史缺失的回调。本次读取到关联任务仍 cancelling / attempt unknown / result=null，最新观测码 SESSION_BINDING_UNAVAILABLE，没有把“代码已合入”当成该生产任务已停止。

## Product Design 与 User Stories

- 用户能明确看到新任务未开始，以及工作区正在等待旧执行的终态证明。
- 运维能从执行结果追到阻塞执行和会话，并区分回执缺失、损坏、非终态。
- 已知未开始的新任务按 failed 归档；旧执行的未知结果和写入围栏保留，不能据此自动重派或释放旧租约。

不改 UI、轮询策略、生产任务状态、凭据或模型路线。新增内容都是协议字段和内部错误码，符合 i18n 的协议/日志豁免。

## 样本证据与时序

[脱敏样本证据](sample-evidence.json)只含任务状态、预算、事件时戳和启动文件元数据，不含任务正文、私有 capability context、密钥或原工具参数。只读 SQLite 使用 mode=ro 和显式事务；没有重放任务或改生产工作区。

| 时间（Unix ms） | 可证事实 |
| --- | --- |
| 1793703036812 | 创建任务；executor=claude，new_session 散目录目标；maxTurns=0、timeoutMs=0、deadlineMs=0 |
| 1793703037216 | CLI attempt 开始准备；usedSteps 被调度层计为 1，不是 Claude 工具次数 |
| 1793703039577 | Python 记录 workspace_prepared 与 started；这只是收到 tmux/runner 回执，并不证明供应商 CLI 已接收 prompt |
| 1793703039676 | runner 的 result.json：failed、WORKSPACE_OUTCOME_UNKNOWN、exitCode=-1 |
| 1793703039740 | task.started 事件落盘，甚至晚于 runner 失败；事件投影不等于实际 CLI 启动时间 |
| 1793703040701 | attempt 终态落盘；随后 task.result → 验证 → task.failed（1793703041057） |

从创建到 runner 结果为 2864 ms；到 attempt 持久化为 3889 ms。没有把二者混称同一耗时。工作区准备和 runner 启动的精确子步骤时间没有独立日志，只有文件元数据和程序顺序，不能编造更细时戳。

执行目录 `agents/executions/e86bb40abe53d69ee82cdd37fd6210997e7be6e1a4d3435271e226001223323b` 存在 spec.json、receipt.json、started、run.lock、result.json；**没有 prompt.txt**。receipt 只有 session/workspace，无 provider binding；SQLite agent_conversation_id=null。日志 `/home/ai/.roami/logs/2026-1103-1850-00cy.log` 只有 `WORKSPACE_OUTCOME_UNKNOWN`。目标 agent-governance/ 及三份 HTML 不存在。

实际路径：

1. `dispatch/runner.py:63` 的 charge_budget 记一次调度消耗；`executors/roami_cli.py:81` 构造 persistent=true、permission=auto、timeoutSeconds=0 的 launch spec。
2. `internal/agentexecution/execution.go:Launch` 校验目标/二进制、持久化 spec，prepareWorkspace 规范化散目录并登记 workspaceId；创建会话 `2026-1103-1850-00cy` 执行 `roami agent execution run`。
3. `execution.go:Run` 持久化 started 标记后进入 `persistent-session.go:17`。started 表示 runner 防重放标记，不表示 CLI/工具已启动。
4. `persistent-session.go:31` 的 PrepareInteractive 可运行 **claude --help 能力探测**并生成 scoped hook settings；它不是任务 CLI，也不调用模型或业务工具。历史未保存 probe 输出，不能断言当时具体版本。[当前只读 CLI 探测](cli-probe.txt)为 Claude Code 2.1.317，支持 auto 权限档及上述启动参数，仅证明现在的安装能力。
5. `persistent-session.go:35` → `workspace-lease.go:98` 的 claimWorkspace 发现旧 writer 的 result.json 缺失，拒绝 admission。旧代码仅返回一个普通字符串错误。
6. `persistent-session.go:61` 的旧 failPersistent 只把 err.Error 写为 summary，手工填 -1。在 `prompt.txt` 写入、RecordAgentSession、`syscall.Exec`（同文件 :55）之前返回。没有供应商 stderr、工具调用或模型请求。
7. Python `roami_cli.py:323` 的 result 原样透传 Go result；`dispatch/tasks.py:689` 的 report 持久化，再经 `dispatch/runner.py:392,552` 验证/完成。此次不是 Python 吞掉已有 stderr，而是 Go 只产出了泛化错误码。

## 工具、能力、权限、cwd、模型与预算核对

| 层 | 证据与判断 |
| --- | --- |
| cwd / workspace | spec.directory、receipt.workspace.directory 与旧 binding.directory 同为 `/home/ai/.roami/workspaces/agent-coding`；workspaceId `ad894949…` 已登记。非 WORKSPACE_STALE，失败在写入准入 |
| CLI 参数 | spec persistent=true、permission=auto，无显式 model；`internal/agent/claude.go:30` 构造 `--permission-mode auto --session-id …`，scoped hooks 经 spawn 注入 `--settings`。没有 prompt.txt，故任务命令未执行；未将潜在参数兼容性问题认定为本次原因 |
| Skill / MCP / CLI | `tools/professional_capabilities.py:81` 生成按 task/run/revision 绑定的私有 context，`roami_cli.py:127` 将平台入口前置到 prompt。样本 spec 中有能力说明；它不代表 CLI/MCP 实际调用。SQL 未发现本任务 capability.started/completed；不能凭安装清单断言某个集成当时可用 |
| 权限与工具调用 | permission=auto 是供应商权限档；工作区 writer 围栏先于接收任务。首次工具未发生，不是工具 JSON 参数解析错误，也没有证据指向 MCP schema/权限拒绝 |
| 模型和凭据 | 没有显式 model，也没有建立 provider conversation；实际任务未走模型请求/凭据解析。没有证据将此次归为 MODEL_HTTP_401 或 MODEL_DEADLINE；未读出密钥、未改路由、未用替代模型试跑 |
| maxTurns / deadline | `dispatch/tasks.py:392` 默认零表示不限；`runner.py:70` 只在非零时比较；`roami_cli.py:103` 将零转 timeoutSeconds=0；`execution.go:executionContext` 零采用 WithCancel。因此不是“预算为零立即超时” |
| usedSteps=1 | charge_budget 在调用 executor.run 前自增一次；不能用来推断 Claude 调过一次工具 |

## 旧执行为什么阻塞

writer.json 位于 `agents/workspace-leases/66e353a39702a8ae69812318032e143e4410af6783018592589cc29f9de75235/`，绑定旧任务 `365dec53f78d4ec784c6d4433d0d0c26`、旧会话 `2026-1029-1407-009d`。writer 文件与旧 execution 目录的 mtime/ctime 均停留在 10-29（早于样本），支持“并非排查期间才被替换/删除”的判断；元数据保存在样本证据。旧 execution receipt=running，result.json 缺失；lifecycle=unknown、unknownReason 未记录，仍有 4 个 pending 工具。旧 SQLite attempt 曾收到 succeeded 的报告，但当前 task=failed；**执行器自报成果与真实停止证明是两条独立链**，不能用数据库的自报结果替代 Go 终态回执。

核查原 Claude transcript（provider `af741332-56e9-4526-8609-d71d40bb0451`）：287 个 tool_use、287 个匹配 tool_result，无未匹配 ID；以下四个 lifecycle pending ID 均为 Read，均已有 is_error=false 的结果：

| pending tool ID | transcript 调用 / 结果时间（UTC） | 结果 content 的 UTF-8 JSON 字节数 |
| --- | --- | ---: |
| call_00_albpmg34twooy6uuamyykmov | 匹配记录无 timestamp，不能补造 | 563712 |
| call_00_m059kggkt2ba3skuzaqljyoz | 2026-10-30 02:37:39.140 / 02:37:39.249 | 502600 |
| call_00_no3su4iuq9r1m4u6pkbpnc3v | 2026-10-30 02:38:07.097 / 02:38:07.193 | 604624 |
| call_00_ghw3kjmiy3k7pgash6rwdl0l | 2026-10-30 02:38:14.458 / 02:38:14.604 | 505612 |

进一步只读核对旧会话终端日志（5,561,666 字节，SHA256 见样本证据），明确包含 `PostToolUse:Read hook error` 及 `Failed with non-blocking status code: AGENT_INPUT_TOO_LARGE`。日志是 TUI 重绘流，286 处 hook error 字样不是 286 次独立故障，不纳入任务频次。四个 pending Read 的结果 content 单独序列化就超过 100000 字节；表中数值不是缺失的原始 hook envelope 大小。

**工具调用层出错点已经定位到旧 hook 输入边界**：PR #524 之前，`cmd/roami/agent-execution.go` 的 event/notify 分支调用 `agentInput`，后者在 `cmd/roami/agent.go:355` 只读 100001 字节、超过 100000 返回 AGENT_INPUT_TOO_LARGE。PostToolUse 的 tool_response 包含大 Read 结果，因而在 ObserveSessionEvent 之前丢失完成回调；实际 Read 已成功，生命周期 pending 未清理，完成证明没有落盘，旧 writer 留存，随后新任务在 claimWorkspace 被拒绝。日志没有原始 envelope/ToolID，不能把每个重绘错误逐条绑定为四个 ID 的独立回调，也不能指定首个 unknown 的准确事件。

该旧缺陷已由 [issue #523](https://github.com/ybz21/Roami/issues/523) / [PR #524](https://github.com/ybz21/Roami/pull/524) 跟踪并于 2026-10-30T05:02:49Z 合入，晚于上述三条带时间的错误工具结果。当前 `cmd/roami/agent-execution.go:219` 使用 sessionEventInput；`internal/agentexecution/session-lifecycle.go:477` 的 ReadSessionEvent 接受有界 64 MiB envelope，丢弃未使用的 tool_response，仅限制实际生命周期元数据为 100000 字节。普通 CLI 输入上限不变。此次不重复修改已修代码，补跑既有大 hook 回归；合入修复不会自动把旧 unknown 转成已停止。

这证明“生命周期 pending”不等于工具失败。`session-lifecycle.go:257` 在 state 非 busy、turn 不匹配或缺 ToolID 时仍拒绝信任后续事件，不能拿当前 transcript 成功结果当成进程停止证明。没有手工清空 pending、删除 writer.json 或杀用户会话。

## 历史关联和频次

[本次频次快照](frequency.json)：2026-11-03T11:18:06Z，本节点 55 个任务、79 次尝试（含历史 revision）；29 failed、6 unknown。6 个 unknown 中，2 个没有 result，分别属于仍 cancelling 和仍 running 的任务，不能都算作已失败。统计 errorCode 优先，否则为全大写 summary；自然语言/缺失归 other/no summary。只统计 attempt，不把日志重复报错累计为任务，不把目标正文提及同项目就算项目任务。

| 根因簇 / 错误码 | 次数 | 是否与本次同根因 |
| --- | ---: | --- |
| 新 CLI 被旧 writer 围栏拒绝：WORKSPACE_OUTCOME_UNKNOWN | 1 | 本次确证；上游旧大 Read 回调被 AGENT_INPUT_TOO_LARGE 拒绝，后续旧终态缺失，同时新启动诊断缺失 |
| native 未确认副作用：NATIVE_WORKSPACE_OUTCOME_UNKNOWN | 2 | 不同；前报告在两次内层事件中均找到 TOOL_OUTCOME_UNKNOWN（browser_open / browser_act） |
| 未确认工具副作用：TOOL_OUTCOME_UNKNOWN | 2 | 不同；安全保护，不能猜成功或自动重放 |
| 会话忙：SESSION_NOT_IDLE | 1 | 不同；目标会话准入，当前已按原 launch key 退避；不是旧目录 writer 的 missing result |
| 目录/分支失效：WORKSPACE_STALE | 1 | 不同；身份与 Git 归属验证拒绝 |
| 旧混合超时/中断：EXECUTION_DEADLINE_OR_INTERRUPTION | 5 | 仅相同可观测性问题，历史不能进一步拆分；#590 已区分新记录 |
| 认证：MODEL_HTTP_401 | 1 | 不同；上游 HTTP 401，不能用此次 pre-exec 失败解释 |
| 模型等待：MODEL_DEADLINE | 1 | 不同；缺当时配置/响应证据，不能断言具体网络原因 |
| 参数修复无进展：TOOL_ARGUMENT_REPAIR_STALLED | 1 | 不同；循环保护，前次已核对 #397/#359；不移除保护 |
| 旧步数限制：AGENT_STEP_LIMIT | 8 | 不同；历史策略，当前已不限 |
| 浏览器依赖：BROWSER_DRIVER_UNAVAILABLE | 2 | 不同；不重启生产浏览器验证历史 |
| 旧会话无绑定：SESSION_LIFECYCLE_UNAVAILABLE | 2 | 不同；无可靠生命周期跟踪 |
| session 目标冲突 / native 不支持目标 | 1 + 1 | 不同；CODING_SESSION_TARGET_CONFLICT / NATIVE_TARGET_ADAPTER_NOT_IMPLEMENTED |
| 项目/工作区启动传输：PROJECT_PROVISION_UNAVAILABLE / NATIVE_WORKSPACE_UNAVAILABLE | 1 + 1 | 历史根因缺失，前报告已修透传/准入；不能归同因 |
| 通用失败 / 自然语言失败 | 1 + 1 | 证据不足，不能归同因 |
| 无 result 的 unknown | 2 | 当前观测未收敛，非确定失败；其中关联 f169 任务仍 cancelling |

该关联链涉及 1 个旧 writer 和 1 次新增被拒绝尝试；旧 writer 的 attempt 自报 succeeded，不额外计为一条 WORKSPACE_OUTCOME_UNKNOWN。上述错误码频次不等于新代码缺陷次数，不能把所有 unknown 视为同一种工具错误。与 11-02 快照相比新增本样本 failed 1、当前任务 running 1；关联任务从 running 变 cancelling，其 unknown attempt 仍无 result。

复核口径：

```sql
BEGIN;
SELECT state, count(*) FROM tasks GROUP BY state;
SELECT state, json_extract(result_json,'$.errorCode'),
       json_extract(result_json,'$.summary'), count(*)
FROM task_attempts
GROUP BY state, json_extract(result_json,'$.errorCode'),
         json_extract(result_json,'$.summary');
COMMIT;
```

## Technical Design 与修复

`workspace-lease.go:98` 把泛化字符串改为带安全结构的 workspaceClaimError，Error() 仍返回 WORKSPACE_OUTCOME_UNKNOWN 兼容既有 admission 协议。区分 WORKSPACE_PRIOR_LAUNCH_INVALID、WORKSPACE_PRIOR_RESULT_MISSING、WORKSPACE_PRIOR_RESULT_UNREADABLE、WORKSPACE_PRIOR_RESULT_NOT_TERMINAL。阻塞执行以 launch key 的 SHA256（执行目录名）记录，不导出原 key、工具参数或私密异常文本；有可读 receipt 时带 blockingSessionId。

`workspace-lease.go:41` 统一构造结果；`execution.go:Result` 加字段。summary 提供具体 reasonCode；errorCode 保留原 WORKSPACE_OUTCOME_UNKNOWN。executionStarted=false 和 exitCodeSource=not_started 明确 -1 是兼容占位，不是假冒进程退出。failure.phase=workspace_claim，保留阻塞执行/会话。

普通 one-shot `execution.go:393`、常驻 TUI `persistent-session.go:35`、结构化 one-shot `structured-process.go:146`、结构化初始 turn `structured-session.go:101` 均使用统一结果并原子落盘。Python 现有 **result 展开透传** 已足够，不改生产 Python；新增测试验证 result → poll → SQLite attempt → verify → detail 和 task.failed 事件，保证底层诊断可供 Main 和执行记录读取。

状态仍是新任务 failed；没有把新任务的 executionStarted=false 推广为旧任务停止证明，也不标旧工作区 outcomeKnown=true。原终态规则和 writer 所有权不变，拒绝不能覆盖旧 writer.json。

## 验证与验收边界

[基线反例](baseline-verification.txt)：Go overlay 读取 `4b9341af` 的原生产源码，不切分支、不改工作区，构造旧 writer 无 result 的条件，真实调用旧 failPersistent 后得到与现场相同的最简结果；断言缺 executionStarted 和阻塞证据按预期失败。这里是故意失败的缺陷证明，不是通过的测试。

[Go 定向验证](targeted-go.txt)：缺失/损坏/非终态回执均保留分类；真实 Service.Run 的 Claude、Codex、pi 三条路径均先拒绝 workspace，再由 Status 读取持久化诊断。假 CLI 允许 --help 探测，实际任务调用会触碰 marker；验证 marker 与 prompt.txt 均不存在。测试使用伪身份传输和临时目录，不触及用户 tmux。现有续作及 native workspace 回归一并运行。

[既有大 hook 修复回归](existing-hook-fix-verification.txt)：使用 600000 字节 content 配方验证 PostToolUse / PostToolUseFailure 都能清除 pending 并完成精确会话；损坏/超限元数据仍拒绝，真实 CLI 输入入口接受大响应而普通 CLI 100000 字节规则保留。这里验证既有 #524 的修复，没有重复改码或重放生产工具。

[Python 定向验证](targeted-python.txt)：51 passed，验证诊断字段完整穿过持久化/验收链，failed 后不再 poll；包含已有未知副作用和原因链保护。

[隔离 CLI 验证](isolated-cli-verification.txt)：实际构建 Go CLI，使用 `scripts/dev/isolated-roami.sh` 创建私有 tmux server，在临时工作区植入缺失终态的旧 writer，再走 launch → tmux runner → status 全链路。结果为 WORKSPACE_PRIOR_RESULT_MISSING、executionStarted=false，且 prompt.txt/任务 CLI marker 不存在、旧 writer 未变化。验证后通过同一隔离入口 --stop 清理，未使用用户 tmux server。

[完整质量门禁](quality-verification.txt)通过：`env -u ROAM_HOME bash scripts/dev/quality/check.sh full`，Go 全仓测试、Python **3258 passed / 48 skipped**（728.56s）、ruff lint/format、i18n 4790 keys、hover、typecheck、生产 build、secret scan、staged policy 全通过。ROAM_HOME 仅对检查进程移除，沿用前次报告已证实的测试环境隔离处理，没有改节点配置。提交使用仓库标准 pre-commit quick 钩子，不绕过钩子。PR 附真实回归输出截图，由 pr-shot.sh 上传到 pr-shots 分支，截图不进入 main。没有改前端，手机触屏验收不适用于本次协议诊断改动。假 CLI 验证启动边界，不代表真实供应商模型/工具在线验收，也没有调用生产模型或未知写操作。

## 未修复项与恢复条件

1. 生产旧 writer 的大 Read hook 输入拒绝已有终端日志证据，首次 unknown 的精确 envelope/事件顺序仍缺失；四个 Read 已有 transcript 结果不能用作整个会话停止证明。需由原执行身份与可信进程停止边界核对后恢复，不能删除租约绕过保护。本 PR 不部署、不恢复旧任务、不补做原三份 HTML。
2. 旧历史 result 不会被新字段追溯改写；此次报告补足样本证据，新诊断仅对采用新代码的后续失败生效。
3. 本修复范围是 workspace admission。其它 failPersistent 启动失败、供应商 CLI 参数兼容性、后续 exec stderr 的完整监督均未据此扩大修改；没有证据证明它们造成此样本。
4. 旧 lifecycle 未留原始 hook envelope，不能确定首个 unknown 的准确时戳/事件身份；终端日志已定位 AGENT_INPUT_TOO_LARGE 输入边界。#524 的大响应修复和 #596 的 unknownReason 不回填旧数据；需可信停止证据恢复原会话。
5. PR 待审阅和部署后独立验收；报告与本地测试不等于生产恢复完成。
