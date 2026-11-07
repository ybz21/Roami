# Automatic review, publication and collection

Use this mode when the user asks the project to operate autonomously. Keep the
original project Main, roles and provider conversations. A requirement to work
automatically is not evidence that the publisher, scheduler or accounts are
already connected; discover the actual host capabilities and implement gaps.

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

## Publish and reconcile

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
