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
    dashboard/{index.html,style.css,page.js}
    agents/{main.json,main.md,team.json,swarm.json}
    connectors/collect-SOURCE/
      SKILL.md
      scripts/collect.py       # Python 按需提供
      references/mcp.md        # MCP 按需提供
      connector.json           # 来源/指标绑定；与 SKILL.md 同包
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


## 用户确认的 Connector 位置

Connector Skill 统一放在 `/home/ai/codes/roami-promotion/.roami/okr/connectors/`
这一层，而不是项目 `skills/` 下：

```text
.roami/okr/connectors/collect-github/
  SKILL.md
  connector.json
  scripts/collect.py             # Python 实现时提供
  references/mcp.md              # MCP 实现时提供
```

项目 `skills/` 可继续保存规划、执行、复盘等工作流。开发/编辑原始 Skill 仍是全局
canonical `okr-development`，它生成上述 Connector 包。ProjectSkill discovery 要支持
`connectors/<name>/SKILL.md`，并在 project 命名空间读取其脚本/引用；不能把别的项目
同名 Skill 合并进来。当前只支持 skills 路径的 reader 必须随协议一起升级。

只读核对的真实目录有七个 schema1 Connector：github-stars/github-forks 是内置
GitHub，另五个是 manual，当前仅有 connector.json、README 和 Go 实现参考，**还
不是 Skill 包**。迁移先补兼容协议与确认读取，再逐包转换；旧文件、来源键、指标 ID、
观测与已确认历史保留。本轮没有移动或改写这些真实文件。

## 看板定义与组件选型

优先支持用户自己的 HTML。`dashboard.json` 是唯一看板入口描述；兼容现在的
schema1/widgets，拟议 schema2 可选择 HTML 渲染并声明可读的数据绑定：

```json
{
  "schemaVersion": 2,
  "renderer": "html",
  "entry": "dashboard/index.html",
  "bindings": {
    "github-stars": {"metricId": "github-stars", "range": "14d"},
    "github-forks": {"metricId": "github-forks", "range": "14d"},
    "channel-summary": {"datasetId": "channel-summary"}
  }
}
```

HTML、CSS、JS 都放在 `.roami/okr/dashboard/`，与绑定一起确认版本。组件数量与
布局由这个项目决定；每个指标独立成卡。普通运行态不出现 HTML/JSON 配置表。

| 内容 | 实现选择 | HTML 作者如何使用 |
| --- | --- | --- |
| KPI 数值、日期、增量与状态 | 小型展示组件，复用格式化与主题令牌 | 自己写 HTML，或选模板中的数值卡 |
| 折线、柱状、分布 | 复用仓库已有 Apache ECharts，按需打包图表类型 | SDK 返回数据；页面调用 setOption 更新 |
| KR 进度 | 受控的进度组件；目标、单位、未知值统一处理 | 读取 KR 投影或模板组件 |
| 明细表 | 原生语义 table 或既有 antd Table；大表分页取数 | 读取声明的 dataset，不把数据库整表送前端 |
| 说明/富文本 | HTML/CSS 布局或受控 Markdown | 与图表并列，不在主应用 DOM 插入任意脚本 |

ECharts 不是新引入的图表框架，现有 OkrTrend 已采用其 core/LineChart/CanvasRenderer。
后续把图表纯渲染层复用给默认 React 看板与 HTML SDK。数据与图表配置分开，采用
`dataset`/系列映射，数据变化通过 `setOption` 更新，容器变化用已有 ResizeObserver。
参见 [ECharts dataset](https://echarts.apache.org/handbook/en/concepts/dataset/) 与
[动态数据](https://echarts.apache.org/handbook/en/how-to/data/dynamic-data/)。

## 数据怎样保存

沿用已经落地的确认快照协议，不新增一份容易失配的“最新指标库”：

```text
data/observations.jsonl                     日期化观测导出，含更正版本
state/confirmed-revisions/13-<id>.json       不可变 workspace/证据快照
state/current.json                         原子指向一份完整快照
```

Skill 返回候选数据；Go 宿主验证来源、指标、日期、单位、有限数值和当前 revision，
写事实导出与不可变快照后，最后原子替换 current.json。前端由指针取整个一致版本，
不会读到写一半的 JSONL。不要直接修改 JSONL 或让脚本覆盖 current.json。

当前真实 `GET /api/projects/:pid/okr` 返回这份确认工作区；自定义 HTML 的数据投影
接口待新增，建议 `GET /api/projects/:pid/okr/dashboard-data?range=14d`。后者只返回
manifest 中获准的 dataset、有限日期范围与显示需要的列；大明细必须分页，不把
完整观测历史/所有账号数据塞进 HTML。ETag 覆盖 dataVersion 与采集状态版本。

运行时数据库保存 schedules/jobs/runs、租约、下一次时间、重试和幂等键，不作为
文件化项目指标的第二主库。大明细可留在来源数据库，Connector Skill 输出统计结果
与证据。后续超过快照规模上限时，用明确版本化迁移引入事实库，不能静默双写。

## 用户自定义 HTML 如何读

HTML 不直接读服务器路径、JSONL 或 SQLite，也不拿项目鉴权凭证。主应用绑定当前
project，读取上述只读投影，通过专用 MessageChannel 给看板 iframe 注入 `okr` SDK。
以下是**拟定 SDK 契约**，产品后端尚未提供：

```html
<h2>GitHub star</h2>
<strong id="stars">未知</strong>
<script>
(async () => {
  const draw = data => {
    document.getElementById('stars').textContent = data.latest.value ?? '未知';
    // 用户也可以在这里调用 chart.setOption(...)。
  };
  draw(await okr.data.read('github-stars'));
  const unsubscribe = okr.data.subscribe('github-stars', draw);
})();
</script>
```

`read(datasetId, {range?,cursor?})` 返回获准数据；`subscribe(datasetId, callback)` 返回
取消订阅函数。返回值含 snapshotId/revision、latest、points、source、asOf、capturedAt、
quality/lastError；`null` 表示未知。宿主把绑定主题与 locale 一起提供，用户可以完全
自己设计 HTML 和组件，不必写 React，也不必选固定的 UI 图表。

```text
Python/MCP Connector Skill
    → 候选观测 + 证据
    → Go 校验 / 确认快照 / current.json
    → 项目只读数据 API
    → 当前看板专用消息通道 / okr.data SDK
    → 用户 HTML / ECharts / 表格
```

宿主复用页面级更新/事件与缓存；同页多个卡片共享一次取数，不各自轮询。发布新
revision 后宿主重新获取投影并推给订阅者；隐藏/离开看板暂停，恢复时对账最新版本。
采集失败只改变健康状态，数据版本和上次有效值不变；状态更新也能通知 HTML。
SDK 不能提交采集结果、派工、切换 project 或调用任意 Roami API。

自定义 HTML 不在主应用同源 DOM 执行。iframe 开脚本但不开 allow-same-origin；
打包确认的 HTML/CSS/JS、SDK 和本地 ECharts 资源，CSP 限制资源与网络。父端只接受
本 iframe 的握手和通道，绑定 project、看板版本与允许 dataset；页面刷新/切换即销毁
旧通道。不把鉴权 cookie、文件路径或能力令牌传进 iframe。不沿用通用文件预览的
同源访问方式承载可执行看板。隔离语义依据
[HTML sandbox 标准](https://html.spec.whatwg.org/multipage/iframe-embed-object.html#attr-iframe-sandbox)。

[本目录的 HTML/SDK 演示](dashboard-example.html)仅使用静态 fixture，不代表真实 API、沙箱加载器或生产
Skill Runner 已实现；正式实现需要覆盖越权 dataset、跨项目、旧 iframe 消息、畸形
数据、更新去重、退出清理和页面/脚本资源限制。

## 生成 OKR 的 Skill 交付清单

`okr-development` 既创建也编辑。输入：用户对话、已注册项目根、现有确认 revision、
期望目标/周期、模板可选、数据源/口径、职责和调度决定。输出不是一段建议，而是：

1. 完整草稿包：okr.json、dashboard.json、用户 dashboard HTML/CSS/JS、Connector
   Skill（SKILL.md + Python 或 MCP 资源）、team 期望职责、AGENTS/记忆位置与调度草稿。
2. 基于同一投影的运行预览、可核对的变更和校验结果。预览没有注册、派工或定时副作用。
3. 用户确认后的 revision CAS 发布与真实回读。保留原 Main、成员、provider 对话和历史。
4. 只有用户要求且宿主能力已接通时，依据真实登记/派工/调度回执继续；不能把定义或
   HTML 已加载说成取数成功或日更已启用。

模板包随 Skill 的 `assets/templates/` 版本化分发，至少含 `template.json`、dashboard
布局种子、Connector Skill 种子、目标/职责种子与必要资料。模板内容不包含凭证、实例
ID、模拟事实；调度默认关闭。开发 Skill 按用户已有答案填充并校验，缺口留为未知；
人数、KR 和图表数量可以增减。预置内容增长、产品交付、运营指标，支持将用户自己
的 HTML 作为看板起点。编辑场景保留不相关的定义，只把新职责写入期望计划。


可执行脚本的 CSP 限制 fetch/子资源并不等于完全网络沙箱，尤其不能据此承诺任意
用户 JS 绝无出站请求。生产加载器须明确脚本信任与授权范围；若要求严格禁止所有
外联，还需宿主网络策略/代理控制，而不是只加 iframe 属性。样例用于证明只读数据
通道与源隔离，不把它当作完整生产安全实现。
