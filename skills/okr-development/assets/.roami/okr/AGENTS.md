# OKR workflow

Read the project's confirmed goal, sources, team memory and current board first.
One project Main coordinates the bound Swarm. Reuse long-lived members, tasks and
provider conversations; new work becomes a new round, not an r2/r3 replacement.
Declare inputs, owner, dependencies, deliverables and independent acceptance.
A delivery receipt is not completion. Unknown execution needs reconciliation.

Connector Skills live in connectors/<name>/, with scripts/references inside.
Only actual authorized collection produces observations. Never invent zero or
backfill history. Use the registered revision-checked project operations; do not
edit observations.jsonl/current.json or the runtime database to fake confirmation.

Main maintains team.md and decisions.md with date/source/status. Each member keeps
notes in its stable member folder. Store task/revision/run artifacts under the
project's YYYY/YYYYMM/YYYYMMDD/ directory and preserve independent acceptance.
A definition or an idle agent is not an enabled recurring schedule.


## Change a dashboard and publish its data

Main owns the complete result, including the visible dashboard. Read the current
confirmed project context, dashboard.json and dashboard/ assets before changing
them; preserve existing KRs, source bindings, history and team identities.

- Match each requested field to a metricId, unit, account/item and measurement
  window. Add a missing metric when requested; plays are not completion rate or
  watch duration. Record observed zeros, but keep unavailable values unknown.
- JSON widgets reference metrics in dashboard.widgets. HTML views also declare
  metric IDs in dashboard.html.metricIds and render matching cards/data-metric
  elements in dashboard/index.html. Use okr.data.read and subscribe; never
  hardcode collected numbers in HTML or read a private database from the frame.
- Propose config with save before editing managed files. After filesystem edits,
  confirm the complete bundle with revision-checked sync; save rejects pending
  changes. Prefer saving new metrics first so the host generates compatibility
  references, then edit HTML and sync. Preserve drafts on errors and conflicts.
- Main independently reviews source evidence, then records an accepted Connector
  Skill batch, or an unbound manual observation, through the supported operation.
  Do not edit confirmed snapshots or observation exports. Check the real receipt.
- Verify confirmed metric, view reference, accepted observation, dataset response
  and actual rendered value. Report the source's as-of time separately from
  collection time. A chat reply, evidence file or submitted request is not proof
  that the dashboard changed; do not require the user to ask again to save it.

Keep source instructions in Connector Skills and record lasting mappings and
receipts in team memory. A completed collection does not enable a daily schedule.


## 操作手册入口

修改前按任务阅读 [操作手册](manuals/README.md)：
- 改页面/卡片/图表：[看板编辑](manuals/dashboard.md)。
- 取数、存数或卡片为空：[取数与确认入库](manuals/data.md)。
- 群聊、派工、原实例恢复和记忆：[团队协作](manuals/team.md)。
- 开工、交付、复盘、定时和故障处理：[日常运行](manuals/daily.md)。

Main 负责把这些步骤落实到确认回执和实际结果，不能只转发成员的完成声明。
