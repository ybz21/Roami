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

<!-- 以下共同规范与根 AGENTS.md 同步维护，供宿主 projectFiles.workflow 读取。 -->

## OKR 团队共同工作规范

本节是 Main 与所有成员共同遵守的工作约定。项目根目录是整个 OKR 的工作区；路径除特别说明外均相对项目根目录。详细步骤见 [.roami/okr/manuals/README.md](manuals/README.md)，`.roami/okr/AGENTS.md` 补充该目录的操作要求。现有项目的身份、历史、授权与未完成工作必须保留。

### 1. Main、成员、单聊与群聊

- 每个 OKR 使用自己的原 Main，与首页 Main 隔离。开工先读确认 O/KR、`agents/main.json`、`agents/team.json`、实际 Swarm 绑定、当前任务和团队记忆；不要仅凭显示名或聊天中的实例引用选人。
- 用户主要与 Main 对话，由 Main 拆解任务、指挥成员、协调依赖和验收。群聊用于共享进展、问题、交接与决定；@Main/@leader 要对应本项目真实 Main，成员单聊与原生入口要对应同一稳定成员及其真实会话。
- 群聊发言、提及或投递成功不等于已派工或已完成。Main 用宿主受管 register/plan/steer 入口登记、派工和续派，检查当前 task/revision/run；用自己的 `swarm_post` 身份回报，不能用人的 `swarm say` 给自己下指令。
- 同一职责复用稳定 memberId、原任务及 Codex/Claude/OpenCode/Pi 原对话。新一轮追加任务，不新建 r2/r3 替代成员。会话关闭或结果未知，先核对原身份与停止/恢复证据，不创建替身绕过失败。
- 每项任务写清目标、输入、范围、交付路径、依赖和验收。成员在群聊提交当前轮次、文件和证据；Main 独立读取并核验后接受。成员自述、空闲终端和旧轮次文件不能替代验收；具体账号发布仍遵守内容授权和平台回执。

### 2. 看板怎么做、数据怎么取与保存

- O/KR、实施手段和指标在 `.roami/okr/okr.json`；展示定义在 `dashboard.json`；用户 HTML、JS、CSS 在 `dashboard/`。看板只展示数据，每个独立数据表或指标组一张卡片，明确名称、单位、统计对象、窗口和截至时间。
- 新字段先定义稳定 metricId，核对账号/稿件、累计或时间窗口、单位及 source 绑定。JSON widgets 引用该 ID；HTML 同时把它加入 `dashboard.html.metricIds` 并在页面/JS 使用同一 ID。不要把播放量写到完播率，或改名套用另一指标历史。
- 自定义 HTML 等待 `okr.ready()`，用 `okr.data.read(metricId)` 读取确认数据、`okr.data.subscribe(metricId, callback)` 更新展示。数字读 `latest.value`，趋势读 `points`，显示 `asOf`/质量状态。复用模板 `dashboard/page.js`，图表按需用宿主提供的 ECharts；不要硬编码数字、把密钥放进页面或从 iframe 直读 DB/私有接口。
- 取数入口是 `.roami/okr/connectors/<名称>/SKILL.md`。Python 放该 Skill 的 `scripts/`；MCP 在 Skill 内说明实际工具、授权账号、输入和字段映射。同来源多个指标尽量一次采集，保留原始响应、账号/稿件身份、平台截至时间、采集时间、单位及 SHA256。
- 数据成员交候选与证据，Main 独立核对后通过宿主 `record` 确认 Skill 批次或未绑定的 manual 观测；内置来源按当前宿主能力使用 `collect`。来源失败保留旧值；缺失保持未知，只有证据明确给出 0 才记 0。
- 文件包保存定义与确认快照，`data/observations.jsonl` 等保留导出历史，`state/current.json` 指向确认版本；运行时 DB 保存宿主管理的身份、索引和调度状态。全部通过支持的操作更新，不直接改 DB、JSONL 或确认指针“填看板”，不另建一套页面私有数据源。
- 修改定义前读最新 revision。未编辑文件时用 `save` 提交完整配置；文件已改时用 `sync` 校验确认，不能反复 save 或删状态绕过 pending changes。冲突保留草稿并重新合并。
- 完成必须逐段核对：确认指标 → 展示引用 → 同口径确认观测 → 看板数据接口 → 实际卡片。取到数、候选文件存在或请求已提交都不代表看板更新。操作见 [看板](manuals/dashboard.md) 和 [取数](manuals/data.md)。

### 3. 每个子智能体的个人长期记忆

- 固定位置是 `.roami/okr/memory/members/<稳定成员ID>/memory.md`；不要用显示名、日期或执行轮次代替成员身份。成员跨天、跨轮次继续同一份个人记忆与原 provider 对话。
- 开工读自己的记忆、团队记忆、当前任务与最近复盘；收工记录已验证的做法、来源/证据路径、失败及恢复方法、尚未完成事项和下一步。保留日期、适用范围和状态；不要粘贴整段聊天或把“打算做”写成“做完”。
- 个人文件由该成员按实际文件权限维护；共享知识通过群聊提议，由 Main 核验并合入团队记忆。宿主只开放 Main 写共享记忆时不能绕过权限；仅支持 team.md 的接口不能当作任意个人文件的写入口。个人经验不会自动成为团队规则。

### 4. 团队记忆与重要决定

- `.roami/okr/memory/team.md` 放可复用事实、职责约定、指标/来源映射、已验证流程及当前有效经验；Main 负责合并。`.roami/okr/memory/decisions.md` 放用户决定、授权边界、重要变更和未决问题，注明日期、来源、负责人、状态及替代关系。
- 群聊交接使用“本轮任务与结果、产物路径、证据、阻塞、建议的记忆更新”；Main 先核实，再按支持的项目记忆或 Swarm 记忆操作读取全文/版本并 CAS 写入。当前项目 memory 操作写 team.md；decisions.md 和个人文件按各自实际文件权限维护，修改前读原文并核对未被他人更改，不伪造通用 memory API。项目记忆与 Swarm 记忆如为不同存储，要明确各自路径及同步回执，不能假定自动同步。
- 更新保留已有知识与历史，冲突后重读合并；更正旧结论要追加来源和更正说明，不抹掉失败。记忆不保存密码、Cookie、Token，不代替交付文件、发布回执或独立验收。

### 5. 按日、周、月、年组织产物与记忆

采用项目约定的 IANA 时区；日期来自真实发生时间。日目录按 `YYYY/YYYYMM/YYYYMMDD/` 组织，任务产物在 `<方法>/<taskId>/r<revision>/<runId>/`；Main 维护当日 `README.md` 和 `manifest.json`，成员只写各自目录。跨午夜继续原运行目录，次日索引引用；旧文件保留原日期，不搬到今天冒充新产物。

| 层次 | 位置 | 写什么、谁维护 |
| --- | --- | --- |
| 日交付与日复盘 | `YYYY/YYYYMM/YYYYMMDD/`，复盘在 `reflection/` | 成员交本轮文件和原始证据；Main 写当日结果、未知、阻塞、验收和下一实验 |
| 周记忆 | `YYYY/reflection/weeks/YYYY-Www.md` | Main 按 ISO 周年/周号聚合实际日期与来源链接；跨月周不重复算，跨年周放对应 ISO 周年 |
| 月记忆 | `YYYY/YYYYMM/reflection/month.md` | Main 汇总本月已验证结果、趋势、实验、失败与下月选择 |
| 年记忆 | `YYYY/reflection/year.md` | Main 汇总全年目标变化、有效方法、长期结论与下一年建议 |
| 长期记忆 | `.roami/okr/memory/` | 将经核实仍适用的结论提炼到个人、团队和决定文件，引用上述证据 |

周期文件在实际复盘时创建；只汇总有来源的工作。区分累计量与增量，记录覆盖日期、数据缺口、来源修订和验收者，不相加重复快照。大素材、原始日志留在真实交付目录，周/月/年文件以结论与链接为主。详见 [记忆手册](manuals/memory.md)。

### 6. Skill 放哪里、用哪一份、如何进化

- 项目流程 Skill 放 `.roami/okr/skills/<名称>/SKILL.md`；取数 Skill 放 `.roami/okr/connectors/<名称>/SKILL.md`，Python/MCP 是其实现方式，不再另立 Connector 插件目录。`SKILL.md` 写用途、输入、权限、步骤、输出/验收和失败恢复；重复的确定性操作放 `scripts/`，字段/口径放 `references/`，可复用素材放 `assets/`。
- 看板编辑目前按 `manuals/dashboard.md`、`skills/okr-planning/SKILL.md` 与 `skills/metric-collection/SKILL.md` 配合执行；需要重复的项目页面生成流程时，再创建项目 `skills/dashboard-authoring/SKILL.md` 并登记，不假称该 Skill 已存在。页面运行资源始终放 `dashboard/`。
- Main 从 `agents/main.json` 声明的 Skills 和宿主确认的 `projectFiles.skills` 获取入口，成员按本轮职责读取明确路径/版本。原生执行器还可用其实际安装的全局 Skills；项目口径以本项目已确认约定为准。全局同名 Skill 不代表项目包已更新，文件存在也不代表自动加载或已执行。
- 经验先写个人候选，Main 结合实际证据提炼团队结论；稳定、重复有效的流程才修改项目 Skill，说明改变原因、适用条件、验证方法与回退方式。先在隔离草稿/离线样本验证，走宿主支持的确认流程，再由下一轮真实结果检验。
- 可推广的经验去掉账号、项目 ID、凭据和私聊后，回提到代码仓库的 `skills/okr-development` 模板/parts/references，经测试与 PR 再分发。新版本不覆盖其他项目定制，也不自动扩大发布、账号或调度权限。详见 [Skill 手册](manuals/skills.md)。

### 7. 定时任务与持续改进

- 定时计划保存在 `.roami/okr/schedules/daily.json`；执行入口使用项目 `skills/daily-operations/`。由操作者通过当前已安装调度插件登记，不能把提案、`autoCollect`、提醒或常驻空闲成员当成通用 Skill 定时器。
- 启用前明确项目和原 Main、时间/IANA 时区、开工/取数/复盘 slot、工作范围、账号与权限、错过执行的处理及重试规则。缺少时间或宿主能力就保留 `enabled=false`，不猜用户时间。
- 优先用既有 cron 的 `exec` 调用 `daily-operations/scripts/wake_main.py`，先 `--dry-run` 检查 projectMainWake，再登记禁用计划、核对后启用；实际命令以 CLI/plugin help 为准。调度器只唤醒本 OKR 原 Main，由 Main 读取计划并续派原成员，不用每次新建对话的 agent action。
- 调度进程只运行明确选定的本项目日程。核对持久任务 ID、实际执行命令、时区、enabled、下一次触发时间、运行者和常驻服务；不因新增本项目任务启动其他项目全部日程，也不临时加个人 crontab。
- 同项目/Main/当地日期/slot 沿用同一请求 key；Main 忙或等用户时推迟，结果未知先查原请求。不得换 key、换成员或绕过 busy 重放；受控触发后核对 Main turn、成员当前轮次、实际证据、看板和验收，再检查下一次真正定时记录。
- 每轮按“计划 → 执行 → 取数 → 核验 → 复盘 → 改进 → 下一轮”闭环。开工选一个有证据可验证的改进点，写假设、指标、观察窗口与停止条件；收工比较结果与基线、记录未知，决定保留/调整/停止。不能从产量直接推断增长归因。
- Main 将验证后的结果写周期复盘和团队记忆，必要时改 Skill、看板或分工，再受管续派原成员；每次改进留来源、版本、验收与回退记录。定时不能代替独立验收或扩大具体内容发布授权。详见 [日常运行](manuals/daily.md)。
