# OKR 运行态、Studio 与 Skill 实现方案

2026-11-05 设计提案。先审阅[运行态](../20261104-okr-main-workspace/index.html)，再看
[Studio](index.html)；[技术方案 HTML](implementation.html)可直接浏览。
本轮原型均为示例数据与本地模拟，不调用模型、不派工、不采集、不注册定时任务。

## 产品设计

运行态用于做事：固定 Main、群聊、成员原对话、目标、数据、交付和文件。团队页将
对话与协作场景放在同一画布，不再有独立的协作页签，也不在场景下面重复展开职责
与状态长表。职责和轮次进入成员详情，实际任务与验收进入任务详情。桌面可以收起
场景释放空间；手机先显示对话，场景在同页按需展开。

Studio 用于开发和编辑这个 OKR：左侧与原项目 Main 讨论，加载 `okr-development`；
右侧优先显示运行预览，项目文件与变更按需打开。不是把配置项排成多张表，也不是
另建一个项目负责人。右侧复用运行态渲染器，避免编辑预览与运行页面两套实现。
“团队活动”指协作动画；Studio 指开发工作台，两者职责与入口分开。

运行态只保留 OKR、数据看板、团队、团队记忆、项目文件。项目文件打开整个项目根；
复盘作为文件查看，不加独立页面。编辑入口是次要动作，不能挤占与 Main 聊天的入口。

## 用户故事

1. 进入项目立即与原 Main 交流；告诉它目标或今天要做的事，它在原团队追加任务。
2. 切到群聊能看到共享回报；切成员只向这一名成员发送，点击进入其原 Codex/Claude
   对话。原 Main、团队和消息来源不被替换，收件人不靠输入中的 mention 暗中切换。
3. 选择模板并聊出目标、KR、实施手段、看板、Connector Skill 与职责，先看效果，再
   确认保存。应用不等于成员已执行或指标已取到。
4. 修改来源或目标时保留历史与草稿；项目已有新修订时显示差异，不静默覆盖。
5. 每天取数失败时仍能看到上次有效值与日期；无来源的数据保持未知，不变成零。

## 目录与权威

```text
PROJECT/
  AGENTS.md
  .roami/okr/
    okr.json
    dashboard.json
    agents/{main.json,main.md,team.json,swarm.json}
    skills/collect-SOURCE/
      SKILL.md
      scripts/collect.py       # Python 按需提供
      references/mcp.md        # MCP 按需提供
    connectors/SOURCE/connector.json
    schedules/daily.json       # 拟新增：调度的确认输入
    memory/{team.md,decisions.md}
    memory/members/MEMBER_ID/memory.md
    data/{observations.jsonl,reviews.jsonl}
    state/current.json
    state/confirmed-revisions/
  YYYY/YYYYMM/YYYYMMDD/
```

- 项目文件保存目标、展示定义、Skill、来源绑定与调度输入。确认快照是页面读取权威；
  JSONL 是同次发布的事实导出，不开放替换 JSONL 来覆盖实时数据。
- 运行时 SQLite 保存成员、实例、任务/轮次、调度、执行、去重和重试。已有 OKR
  SQLite 保留旧归档与项目归属索引，不再成为文件项目的另一份指标事实主库。
- 来源自身的大量明细可以留在来源数据库；Skill 只提交看板需要的摘要与原始证据引用。
- 凭证留在既有凭证/授权系统，不进入模板、Skill 正文、项目 JSON 或交付日志。

## 开发编辑 Skill 与预置模板

canonical 入口沿用 `agent-runtime/src/roami_agent/skills/okr-development/`，安装到
Codex/Claude 使用同一份正文。新增模板资源建议放在该 Skill 的 `assets/templates/`，
避免另建模板引擎与第三套 Connector 扩展协议。原型示例在本目录 `templates/`。

模板包包含版本、适用场景与文件种子：目标/指标/看板、职责计划、项目指引、取数
Skill，以及默认关闭的调度提案。不包含 Main/member/provider 实例 ID、真实凭证、
模拟事实或“已完成”状态。选择模板只生成草稿；目标、KR、图表和人数均可调整。
项目目录、名称与 stable role ID 在实际创建/应用时绑定，不能拷贝别的项目身份。

开发流程：读现有上下文与 revision → 模板/对话形成草稿 → 校验/运行预览 → 显示
必要差异 → revision CAS 应用 → 回读真实文件与发布回执。创建与编辑用同一流程。
未提交 team 的旧客户端继续保留已确认职责；显式空 roles 才是空计划。

## 模块与接口

| 层 | 现有模块 | 增量方案 |
| --- | --- | --- |
| 运行态 | `ProjectOkr`、`ManagedSwarm`、`OkrMainChat`、`SwarmStudio` | 对话与场景合页；移除下方重复 `SwarmRelations`；保持共享 `ConversationComposer` |
| Studio | canonical `okr-development`；项目确认文件协议 | 新增 `OkrStudio`、`OkrDraftPreview`、`OkrTemplatePicker`；复用运行态组件 |
| 草稿与发布 | `backend/okr/project-files.go` 的 workingConfig / confirmedSnapshot / publish | 新增 `draft-store.go` 隔离草稿、模板装配、diff、校验与 CAS 发布；不写生产指针来做预览 |
| 项目权限 | `conversation/project_okr.py`、`tools/project_okr.py` | 项目 Main 才能确认应用；开发终端仍用受权的版本检查 CLI |
| Skill 读取 | `ProjectFiles.Skills` / projectSkills 与 runtime skill readers | 确认整个所需 Skill 包，包含脚本/引用的摘要；当前只读取 SKILL.md 还不足以证明脚本版本 |
| 调度 | Python `dispatch/scheduler.py` / jobs；已有 GitHub `CollectDue` | 新增通用 Skill schedule/run 服务与持久租约；兼容旧采集，避免两套重叠运行 |
| 执行 | 既有 managed worker、shell/process、MCP broker | 绑定项目与只读取数范围；Python/MCP 在 Skill 内执行；Worker 不能直接冒充 Main 更新 OKR |
| 结果发布 | Go 文件化 OKR Store 的 revision 校验与快照发布 | 新增批量观测提交及执行幂等收据，宿主校验授权、来源与确认版本后落盘 |

拟新增的草稿 API（非现有能力）：

```text
POST /projects/:pid/okr/drafts             基础 revision + 模板/编辑输入
GET  /projects/:pid/okr/drafts/:id         草稿、验证与 diff
POST /projects/:pid/okr/drafts/:id/apply   expectedRevision + draftSha + requestKey
```

预览接口只读草稿投影，不创建 conversation/member/task/schedule，不发模型请求。
apply 前后都验证 owner/project，临时文件不能越出注册项目根或通过符号链接逃逸。
冲突返回最新 revision，保留原草稿；不擅自替换来源、团队与旧事实。

## Connector Skill 与日更

`SKILL.md` 是取数工作流入口。Python 是默认适合确定性采集的实现方式，MCP 是可选
能力来源；都遵循相同的来源绑定、输出校验与发布契约。`connector.json` 只保存来源、
指标和 Skill 引用，不执行其中的任意命令。拟议 schemaVersion 2 的例子：

```json
{
  "schemaVersion": 2,
  "skill": "collect-github",
  "metricIds": ["stars", "forks"],
  "source": {"service": "github", "resource": "ybz21/Roami"}
}
```

现有 schemaVersion 1 的 GitHub/manual 必须继续读取。不能只改 JSON 就把 Go 实现
参考升级成可执行脚本；新 schema 与 Metric source/sourceKey 的身份演进须一起迁移。
同一来源的一次请求可更新多个指标，不强迫每个卡片建一个重复 Skill。

调度文件是已确认输入，示例默认关闭，含 Skill、每日时刻和 IANA 时区；宿主注册后
才产生 nextDue 与持久 receipt。停用、改时间或改来源均 CAS 更新，不以常驻 Agent
充当定时器。没有真实时刻决定时保留关闭草稿，不悄悄采用原型的 09:00。

持久执行状态：`queued → running → publishing → succeeded`，失败为 `failed`；
结果不明为 `unknown`，必须恢复同一个 run。语义幂等键包含 project、schedule、
Skill bundle digest、来源身份与指标日期；数据库独占领取租约。重启恢复租约前先
核对旧 writer 是否已停止。失败有限退避，同日重放去重；跨日不补造历史。

Skill 输出为候选观测与证据，至少保留 metricId、date/asOf、数值、单位、来源账号/
资源、capturedAt 和原始证据引用。宿主重新检查所有指标属于本项目、单位/日期范围、
有限数值、当前来源与 Skill 摘要，以及配置 revision。全部验证后批量发布，不能一半
指标来自旧口径、一半来自新口径。失败不推进有效快照指针。

发布窗口内进程断开时，查询同一 run 的发布收据与已确认快照，不能简单重新 record。
Go 发布端把 batchKey、runId、结果摘要与候选快照一起落盘，current.json 提交后即有
可恢复的发布凭证；运行时数据库再登记成功。若在这两步之间崩溃，按同 batchKey
查询已提交文件，不重复追加观测。临时文件或未推进的指针不算发布完成。

调度绑定配置/Skill/source 的摘要，不把每天变化的观测 revision 当作永久配置版本。
每次发布仍读取最新 workspace revision 做 CAS；并发新增观测时只在配置摘要一致后
重新核对，配置或来源已变则停止旧结果发布。批量请求只提交本授权 run 的指标与
证据，不能通过传 projectId/path 转到其他目标。
源端“查数据”也不一定只读，MCP 工具须依据实际 effect/授权判断；未知工具不能自动
认定为只读。Python 运行需复用宿主受管执行与取消证明；cwd 约束不等于 OS 沙箱。
不要用 shell/raw API/SQLite 绕过项目能力的拒绝。

## 长期实例与消息隔离

成员职责、实例身份、任务/轮次分层，复用现有成员与账本。新增一轮保持稳定 member
与原 provider conversation；投递入队不增加“已完成”轮次。进入原生对话前后检查
owner/node/project/member、执行器、workspace、当前 task/revision/run、会话关闭状态。
终端消失只允许可信恢复原 provider 会话，无法证明则待恢复，不新建替身。

旧重复角色需要显式映射和 CAS，不能截掉 r2 后缀自动合并。保留原任务、文件、回执、
来源与验收；不因本轮改版关闭活实例。Main/群聊/成员的草稿和请求幂等键分别保存；
引用只能回到原项目/原会话，不会创建新 Main 或串到首页 Main。

## 分批实现与验收

1. **对话与协作合页**：快捷收件人、原生会话入口、场景收起、去重复长表。四档桌面、
   窄屏粗指针、草稿与消息隔离；真机按用户授权单独验收。
2. **开发 Skill + 模板 + 草稿**：空目录创建、编辑原项目、模板可调、冲突保留，预览
   无运行副作用；文件根、快照、旧客户端兼容和来源身份不能丢失。
3. **Skill 单次执行**：Python/MCP 独立 fixture 真取数、结果校验、批量 CAS 发布，
   重试幂等、部分源失败、版本变化和发布窗口崩溃恢复。
4. **日更与可信恢复**：时区、重启、跨日、租约、去重、退避与未知结果恢复；连续多轮
   保持原成员/原对话，产物与验收分别记录。最后按实际通过的验收关闭对应 issue。

## 当前状态

#681 已合入，提供开发 Skill、team 定义和文件化链路；#682 已合入，提供 Main 优先
对话入口。CLI/Web 已发布 f4792f0a；运行时仍保留 c6fce4d2，内置新增 Skill 激活待
正常升级。Codex/Claude 的开发 Skill 已安装。通用 Skill 日更、模板装配、Studio 草稿
预览与完整 provider attestation 尚未完成。

本轮原型不部署为产品，不触手机，不改路由、费用、账目、busy、真实项目文件或团队。
界面实现草稿保留在 feat/okr-unified-collaboration；Connector 规范提交保留在
feat/okr-connector-skills。原型确认后再接续实现和分批 PR/发布。
