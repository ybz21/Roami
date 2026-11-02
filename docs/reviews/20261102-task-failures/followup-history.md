# 历史会话 attach、原任务续作与附图输入追加排查

基线 `654e16f7`，追加到 [draft PR #597](https://github.com/ybz21/Roami/pull/597)，不合并、不部署。首轮排查见 [主报告](README.md)。

## 范围与证据

本轮同时核对用户所说的“attach”：已有会话追加、原任务续作，以及附图/文件输入的连续传递。只读 SQLite 使用显式 `BEGIN` 获取一致快照，没有初始化生产 runtime、没有向旧会话补发截图或重复业务。

已读 2909 条消息、1327 条工具记录、178 个有用户消息的 turn；需要解包的 native payload 引用为 0，未读到的 payload 为 0。所有持久历史都在该节点当前登记的数据库范围内；没有宣称覆盖已删除记录或其他节点。已选工具的拒绝次数不是失败任务数，也不是独立根因数。[脱敏快照](followup-history.json) 不含原对话全文、私有项目内容、原始图片、附件 ID 或密钥。

| 工具 | 拒绝码 | 次数 |
| --- | --- | ---: |
| delegate | `EXECUTION_DIRECTORY_UNAVAILABLE` | 1 |
| delegate | `INVALID_TASK_TARGET` | 3 |
| delegate | `INVALID_TOOL_ARGUMENTS` | 1 |
| delegate | `REQUEST_COVERAGE_SOURCE_REQUIRED` | 1 |
| delegate | `REQUEST_HANDOFF_REQUIRED` | 2 |
| delegate | `ROUTING_EXPLICIT_SOURCE_REQUIRED` | 11 |
| delegate | `TASK_COMPLETION_RESTART_FORBIDDEN` | 1 |
| delegate | `TASK_TARGET_REVIEW_REQUIRED` | 1 |
| session_send | `SESSION_TARGET_NOT_FOUND` | 1 |
| target_resolve | `SESSION_TARGET_NOT_FOUND` | 2 |
| task_steer | `REQUEST_HANDOFF_REQUIRED` | 1 |
| task_steer | `TASK_OUTCOME_UNRESOLVED` | 1 |
| task_steer | `TASK_REVISION_CHANGED` | 1 |

有 2 条带附件且已经接受的 handoff：

- 2026-10-19 的已有会话发送：来源消息有 1 张截图，delegate 的 target.kind=session。当前实现只向 session 写文字与回报通道；未传入已校验的附件路径/MIME/hash。此代码缺陷可复现；旧目标是否通过其他办法读过图片没有充分记录，不能断言。
- 另一条原任务附图续作：源消息有 1 张截图，操作 payload 和审计副本中的 attachments 都为 0，且缺 sourceUserMessageId；已有 operationId / 成功 tool receipt 能追溯真实源消息。这是实际留存的丢图证据，不能从当前副本无附件推断用户没有附图。

没有公开任何非本产品项目的历史内容。历史中的业务指令只作为调查数据，没有当作当前授权执行。

## 新增根因与修复

| 根因 | Issue | 实施内容与验证 |
| --- | --- | --- |
| 已有会话 handoff 省略附件 | [#599](https://github.com/ybz21/Roami/issues/599) | SessionDispatches 从当前绑定的源消息取附件，先核对所有者、删除/遗忘状态与 SHA256，再将原文件名、MIME、路径和 hash 作为不可信输入写入持久 prompt；保留原 session、请求键和回报通道。重复请求复用回执，未知投递不重发。 |
| 续作读取审计副本，丢失真实来源与任务历史输入 | [#600](https://github.com/ybz21/Roami/issues/600) | professional_brief 只沿任务自身 sourceMessageIds 与当前 origin 读取，使用既有 task_user_request 恢复真实来源及旧 operationId 关系；输入按 artifact ID 去重，不扫描同一 Main 中无关图片。native 分支也从真实来源复制附件，已撤回来源/图片在 revision 推进前阻断。 |
| 版本过期、会话失效、结果未知缺恢复决定 | [#601](https://github.com/ybz21/Roami/issues/601) | Gateway 对 TASK_REVISION_CHANGED、TASK_STEER_PENDING、SESSION_TARGET_NOT_FOUND 给出这次调用未启动的事实与下一步核对动作；未知结果必须区分停止证明和业务结果核验，不暗示盲等就会恢复。stopConfirmed 以明确 inputStopped=true 为准，同时保留 outcomeKnown=false 和未知写入禁止重放。 |

代码定位（路径相对于 agent-runtime/src/roami_agent）：

- `conversation/attachments.py` 的 `verified_attachment_inputs` 提供输入完整性校验；`app.py` 向 SessionDispatches 注入现有 ArtifactStore。
- `conversation/session_dispatches.py::prepare` 在生成持久 prompt 前后验证来源，并优先保留已记录的 delivered/unknown/failed 回执；输入校验失败时不创建 dispatch、不调用目标。
- `executors/professional_brief.py::professional_brief` 解析任务输入 lineage 与真实来源；不会回放旧指令正文，只传当前 delta 与相关文件引用。
- `dispatch/task_revisions.py::_blocked/advance` 保持 revision fence、原执行器与工作区，在源消息或图片撤回时阻断；旧副本缺附件时使用有证据的真实来源。
- `dispatch/tasks.py` 拆分 stopConfirmed 与 outcomeKnown；`tools/gateway.py` 保存可操作的恢复说明。此处是已有 [#398](https://github.com/ybz21/Roami/issues/398) 的观测修正，不代表该 issue 的所有旧未知现场恢复均已完成。

## 已修复旧问题与正确拒绝

- ROUTING_EXPLICIT_SOURCE_REQUIRED 11 次：历史记录中把以前的执行器偏好、旧请求引用或自动路由误写成当前用户的显式选择；当前 Gateway 已提示沿 task_status/task_steer 续作或在新工作中使用 explicitExecutor=null。现有 [#418](https://github.com/ybz21/Roami/issues/418) 的同任务/执行器约束保留，不重复建 issue，也不放宽授权引文校验。
- TASK_REVISION_CHANGED：保留并发保护；新提示要求读取同一个 taskId 的实际 revision、重新核对当前要求，禁止偷偷换版本或新建任务。
- SESSION_TARGET_NOT_FOUND：原目标确实不可用时仍拒绝，提示从原任务绑定和唯一目标发现核对。没有凭“同项目还有其他会话”就猜一个替代会话。
- TASK_OUTCOME_UNRESOLVED：有未知外部副作用时仍拒绝续作；已证明停止也不等于副作用结果已知。只在系统明确提供 navigationRecoveryAvailable 的只读导航范围内恢复。
- INVALID_TASK_TARGET、INVALID_TOOL_ARGUMENTS、REQUEST_HANDOFF_REQUIRED、REQUEST_COVERAGE_SOURCE_REQUIRED：当前协议校验及定向用例保留；修正缺少字段需要改正参数，不能把保护删除。
- TASK_COMPLETION_RESTART_FORBIDDEN：回报回调不能自行产生新用户意图；原任务续作测试覆盖新用户请求可继续、完成回调不能自发重派。
- 图片气泡曾只显示文字卡片的历史 UI 问题已经有旧修复记录，本轮没有把它重复当成新的附件传递根因。

## 验证

- 旧基线 `654e16f7` 通过 `git archive` 提取到临时目录，只切换测试的 PYTHONPATH；未修改工作区源码或生产数据库。针对新增 21 个输入/恢复用例，基线为 **18 failed / 3 passed（4.90s）**，失败均为预期反例，正向保护仍有 3 项原本通过。结果见 [基线输出摘录](followup-verification.txt)。
- 182 项受影响路径回归全部通过（41.35s）；最终附件、回执保留、拒绝说明与既有回报通道 29 项全部通过（6.18s）。
- 覆盖带图与文件发送、缺失/篡改/删除/遗忘、校验期间撤回、旧审计来源、连续两次纯文字续作、native 附图复制、原执行器/session 保留、unknown 不重发，以及 stale revision / pending / missing session / unknown outcome 的拒绝与说明持久化。
- 全仓 quick/full 门禁待完成，完成后补入真实结果。没有运行旧业务、真实绘图模型或旧任务外部写入，因此不声称完成了生产独立验收。

## 保留限制

已删除的旧会话不能靠代码恢复；旧未知写入仍需要真实结果与外部副作用核验；已撤回或实体丢失的旧图片需要用户重新提供原文件。当前修改解决传递、来源与恢复说明，不自动重做历史任务。原任务首次 unknown 缺少旧 hook 日志的证据缺口仍保留在主报告。
