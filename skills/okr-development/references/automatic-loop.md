# Automatic review, publication and collection

Use this mode when the user asks the project to operate autonomously. Keep the
original project Main, roles and provider conversations. A requirement to work
automatically is not evidence that the publisher, scheduler or accounts are
already connected; discover the actual host capabilities and implement gaps.

## Contract, capability and observed result

AGENTS.md and Skills describe the required workflow; they do not prove the host
implements it. Read the current tool catalogue, schemas and capability signals
before listing a step as available. Keep required behaviour, supported operations
and observed receipts separate. A final-reply source review is not a frozen asset
release, a group progress post is not execution, and a data-write receipt is not
a platform publication receipt or an enabled schedule. Report a missing host
operation as a concrete implementation gap instead of claiming the contract ran.

## Authorization and review

Record the user's project, channels/accounts and chosen mode. In an authorized
automatic mode, Main independently reviews candidates and releases the passing
version without asking the user to approve every item again. A blocked account
or missing publishing channel is a capability/access problem, not a reason to
invent a permanent per-item approval requirement. Keep other existing boundaries.

A task may succeed as a draft delivery while still needing content revision.
Therefore task success is not publication eligibility. Main reads current-run
copy, images/frames, subtitles and sources; checks claims against the relevant
current implementation and evidence; and freezes the exact passing text/media
manifest. Do not turn all existing features into future work because an old
pinned README is stale. A changed candidate invalidates its old review.

Bind review to the real project, member/task/revision/run, actual account/channel
and content hashes. Preserve the reviewed production revision/run even when the
same long-lived member enters a later publishing revision; the host must bind
that publishing execution to the original frozen version. A normal continuation
does not authorize changed content. Only use supported host operations and returned schemas;
project files, memory and a member's report cannot mint a host authorization.
The generic template contains no manufactured member, provider or account IDs.

### Host-frozen candidates

Discover `swarm_publication_prepare` and `swarm_publication_review` in the actual
Main tool directory before using them. Their `roami swarm publication ...` aliases
run through the registered Main tool interface, not the host's public CLI. First
independently accept the original member's artifact task with `swarm_verify`.

The author delivers a retained manifest with `identity.taskId/revision/runId` and
`files` entries containing the same identity plus `path`, `bytes` and `sha256`.
Paths are relative to that manifest's directory. Main selects body, title, tags,
images, video, audio or subtitles by those paths and keeps one stable businessKey
per planned publication. The host snapshots exact bytes from the original run's
workspace; later edits and retry calls do not replace an existing frozen snapshot.

Read every returned text artifact completely and read the exact image files so
the real Main model receives their pixels. Then review the returned versionId.
The host records the independent decision against that immutable version. An
approved review still does not mean a publisher/account is connected or a post
is public. Video/audio approval requires a supported linked-media review path;
do not substitute a gallery, filename, subtitles alone or the author's claim.

### Correct prepare inputs before advancing the author

`content` selects files; it does not contain the post text. For example,
`{"body":"01-post.en.txt","images":["01-card.png"]}` selects those exact
`manifest.files[].path` values. Do not add the project/date directory prefix.
`manifest.id` is the retained host artifact ID, never `manifest.json` or a disk path.

Freeze and independently review the whole batch before steering its original
producer into a publishing revision. A prepare error has not produced a frozen
version. Correct input errors using the same businessKey; do not report an
unverified account failure or bypass the missing receipt with a manual claim of
"frozen". Preserve old attempts if the member already advanced; use the current
supported recovery workflow rather than rewriting its history.

## Publish and reconcile

Before replacing a publisher, inspect the project's previously verified route
and retained receipts. A browser or phone workflow is not disproved by an empty
API/MCP directory. Keep the user's actual device/account boundaries; a one-time
read-only acceptance window must not silently become a permanent operating ban.
Record the chosen route and recovery in the project's publishing manual.



Continue the original publishing member with a bounded assignment and frozen
candidate. A revision-only task does not gain publishing duties. The supported
publisher uses a stable business identity for the content in that project/channel;
do not substitute a new tool-call ID or changed version hash to evade deduplication.
Verify the actual platform receipt, account, text and media. Uploaded, submitted,
unknown and public are different states. Unknown results require reconciliation
of the original attempt before retry, rather than another post with a new key.

## Collect, reflect and continue

Give the confirmed platform object to the original data member. Read its Connector
Skill, preserve dated raw responses and use the supported candidate/confirmation
workflow. Failure retains old facts; unknown is not zero. Keep draft, review,
publication and engagement metrics distinct. Verify the rendered confirmed board.

Main reflects from real receipts, confirmation batches and the previous baseline,
then appends lasting knowledge using current CAS and a stable entry identity.
CAS alone does not deduplicate a recovery that rereads a newer hash. Continue the
same members for the next bounded experiment. A task completion callback can wake
Main without proving arbitrary group messages or daily scheduling are connected.

Use the existing project-scoped daily wake workflow with an actual chosen time,
timezone and schedule receipt. Reuse the original Main and daily/event business
slot through interruption; do not schedule action=agent to create replacement
conversations. Prove at least two actual cycles, including review, real platform
receipts, confirmed collection, board updates and subsequent work. A local HTML
simulation is a design artifact, not this production acceptance.

## Read efficiently without weakening acceptance

Deliver a small review.md and manifest alongside the human HTML gallery. Main
fully pages the selected acceptance artifacts using the host's nextOffset. Use
bound project reads for known files and actual image inputs for visual checks;
metadata or a generated report is not pixel inspection. Do not feed a whole
Base64 gallery into the model to review a few images. If the host cannot read the
project, preserve that capability gap rather than widening global roots.

Verify a real Main image review through both the successful file-read receipt and
the subsequent prompt image evidence with the same content SHA. Main image
capability is independent of Worker capability; do not change saved routes or
role permissions to make an audit appear to pass. A correct final description
alone is weaker evidence than the actual image input and original file hash.

Long-history recovery preserves Main, branch and transcript. Keep the original
compaction operation; only a completed operation with a usable snapshot proves
success. A memory.updated event does not. Explicit upstream context rejection is
handled by host fragment budgeting, not by changing saved models/routes or fees.
After compaction verify real continued work and Main acceptance, not only an
offline replay. A compacted summary does not replace fresh host task/receipt state.

## Main 的实际工具入口

先读当前宿主返回的工具目录与 schema；内部日志名称不等于模型可直接调用的工具名。Foundation Main 用 `read` 读取 `artifact://<真实ID>`，而不是猜一个直接 `artifact_read` 调用。文本有 `nextOffset` 时按页完整读取；每页偏移沿用宿主回执，同一验收回合读取当前轮实际字节。图片应进入真实模型图像输入，不能只读文件名、元数据或 Base64 图库。

使用注册命令时，以单条命令和一个 `--input` JSON 传完整参数，不混用同名 scalar flags，不串接 shell 管道/重定向。下列是结构说明，不能拿占位符请求线上写接口：

- `roami swarm verify --input '<JSON>'`：`swarmId/taskId/revision/runId` 全部取当前真实回执；`accepted` 为布尔值、`checks` 为字符串、`artifactIds` 为实际完整读取的当前文本产物 ID 数组。文本验收不授予外部发布权限，也不能把二进制或外部动作伪装成文本验收。
- `roami project okr update --input '<JSON>'`：`operation="memory"` 时 `payload` 使用 `mode="append"`、仅新增的 `content` 和刚读取的 `expectedSha256`；冲突重读合并，保留旧字节。若目录提供专用 memory_append，优先用其实际 schema。CAS 防覆盖，不自动防止业务条目重复。
- `roami swarm post --input '<JSON>'`：Main 具名回告使用原 Swarm 与稳定 `messageKey`，普通状态用 `kind="progress"`。公共 CLI `swarm say` 是人的入口，不能用来冒充 Main 自我唤醒。

成员后续工作走原 task_steer，检查最新 revision/run 后再接续；不能用 legacy session_send 给受管成员另起一条独立工作流。旧直接消息 callback 只是独立回传，`verified=false` 保持不变；不凭该回传完成新任务。路由 guard、完成恢复与独立验收是不同宿主能力，按当前部署实测，不凭仓库文档假设已经上线。

不同 workspaceId 不保证目录隔离，先核对实际目录，共享目录写任务串行。Native 启动前的工作区拒绝只描述新执行没有开始；前一 writer 的停止和结果仍需独立确认。按实际 failure 阶段与阻塞引用对账，不清锁、改 busy、换业务键或复制角色。没有完整启动前证明的未知结果继续保留未知。

## 持续目标与成员提问

先核对宿主目录是否实际提供 `roami swarm goal status/enable/revoke`；缺少时报告入口未接通，不猜命令或新建替代 Main。已有 active 目标直接接续。需要启用新目标时，先读真实版本与项目已确认的分工，按 memberId 选择当前职责；保留的历史成员不因同名加入本轮。引用当次用户的完整目标，按实际 schema 传 `expectedDelegationRevision` 和 `memberIds`。没有当前任务的角色先在真实用户回合完成分工；协调回合不新建替代任务。启用回执、首次唤醒、真实工作完成与每日排期是不同事实。

成员向 Main 提问、报阻塞或交接时，使用当前任务/轮次/执行身份与稳定 messageKey。Main 对实际 postId 回答；普通 progress 不派工。群聊回复不代表成员已执行，仍需原任务继续工作时，先读最新 task_status，再用原 task_steer 接续。人的群聊输入已有真实 Main 用户入口，不再额外造一个协调回合；Main 自己的进度也不能再次唤醒自己。

暂停时保留通知；已停止的同一批次不靠换键/换实例重新执行。要停止整个循环，应在 Main 撤销持续目标或暂停团队；来源遗忘或轮次失效后不继续执行。已冻结、已读取、已回答和已验收分别核对。报告用 Markdown 链接声明真实交付，行内配置路径可以只是输入引用；不因缺失提示重复执行已完成工作。

需要每天运行时，复用项目 daily-operations Skill 的 Python 入口与实际支持的原目标唤醒能力，再登记仅本项目的 cron 范围。既有 cron 的 action=agent 会新开实例；长期团队应使用可核验的原目标调用，而不是定时开新指挥。普通提醒、只读日报、active 目标或首次启动回执均不证明日程已装好，必须核对真实 nextRun/lastRun 和执行结果。通道尚未连接时如实报告；用户已授权的自动模式不永久改为逐条人工批准。

实际发布与音轨审计按完整模板的 [发布操作手册](../assets/.roami/okr/manuals/publishing.md) 执行：沿用已核验的原生通道，转写最终成片而不是文稿，使用真实回执时刻。日汇总不得把成员自己的范围扩成项目事实；索引整理不作为已充分核验内容的投稿前置。公开浏览量、曝光与链接点击分别定义来源和口径，不相互填充。

## Keep human requests literal

Read confirmed configuration, instructions, memory and Skills through bound-project tools. Do not append whole project snapshots or generated operating restrictions to the user message. Unsaved editor drafts are separate untrusted context, not authorization or confirmed facts. Preserve the ongoing goal and explicit boundaries; a narrowly scoped acceptance request does not cancel the automatic operating mode. Native member continuations must use the host-validated human source, excluding recognized historical generated tails.

## Continue after acceptance

For a continuing goal, finish each delivery/verification turn with a bounded next
step on an original task, actual original work to await, or a concrete blocker.
Read fresh task/revision/run identities before steering. A promise to dispatch
later is not a queued job. Finite work, an ended goal period and a real human
pause can finish normally; do not force an unbounded publishing loop.

On hosts returning `SWARM_GOAL_NEXT_STEP_REQUIRED`, recover in the same turn by
reading actual work and continuing it. Do not repeat completed platform actions.
If the actual catalogue exposes `swarm_goal_checkpoint`, record a blocker using
the current swarmId, a brief reason and the real current-turn failedToolCallId.
Guessed tools, malformed inputs and prohibited operations do not prove a blocker.
A checkpoint neither completes the goal nor authorizes publication. Discover the
operation before use; this manual does not claim that older hosts enforce it.

Preserve a previously verified Chrome/ADB publishing route. Missing OAuth or MCP
for an alternative route is not evidence that the working native route is absent.
