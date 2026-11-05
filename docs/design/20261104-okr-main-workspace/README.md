# OKR 固定主智能体与项目目录

[可视设计说明](index.html)

[每个指标一张趋势卡片](metric-cards.md)（2026-11-05）

[Main 优先的团队对话入口](main-first-conversations.md)（2026-11-05）

## 产品设计

一个已注册项目当前承载一个 OKR。这个 OKR 只有一个持久主智能体对话，目标讨论、团队指挥、任务计划和群聊共用此身份；关闭页面只收起视图，停止执行需要明确动作。已有专用团队 Main 优先复用，保留原任务、回执和历史，不迁改旧运行的归属。新建或重开页面不能产生第二个负责人，也不能回退到节点首页 Main。

文件页按目标配置、团队、记忆、数据连接、产物和历史提供直接入口。项目根保留入口说明、规范、配置包和按日期产物；历史输入与旧运行资料集中归档，原媒体字节与时间不改。兼容目录只用于旧链接，不作为新任务的输出目录。

## 用户故事

- 用户关闭再打开同一个 OKR，继续与同一个负责人交流，能看到原讨论与任务。
- 两个 OKR 的负责人互不串话，模型不能把本目标的指令派到另一个项目。
- 已有团队的用户保留其 Main、成员任务和历史；不会因整理入口而重建团队。
- 用户关闭开发会话或空闲终端，不代表其交付通过验收。
- 新成员从项目入口找到目标、规则、团队记忆、当前任务和当日产物；历史资料有迁移索引可追溯。

## 技术设计

运行时新增 owner/project 唯一的持久 Main 索引；现有 project_okr_conversations 继续约束项目工具权限。既有 POST /conversations 的 projectId 创建路径改为创建或复用持久 Main，校验已关联 Swarm 的 owner、project、独占对话和非首页身份，数据库事务串行化并发创建。请求重试保留原有 requestKey 校验。配置仍由项目 .roami/okr 与确认版本管理，运行实例身份由运行时管理。

前端 OkrMainChat 打开时恢复固定实例；旧运行时能力不足时明确提示并保留草稿。已有专属 Swarm Main 可通过现有读取接口恢复；不创建替身。关闭面板不发送 /stop，明确停止仍只针对当前实例。Swarm 创建默认项目 Main；项目 Main 创建团队时目标必须匹配绑定项目。

不加入同项目多个 OKR 的新命名空间；当前身份模型为 project → OKR → Main → Swarm → task/revision/run。后续多 OKR 必须另行版本化迁移，不能直接搬动已确认定义或历史。

## 验收记录

会话收拢审计：/tmp/okr-single-main-cleanup；原主线交接：/tmp/okr-single-main-handoff.md。仅关闭三个已确认空闲、无子会话的本轮会话，关闭前后宿主状态未改变。实现与桌面检查见下，手机没有操作或计为通过。

真实目录已整理：327 个历史原件归档、21 个根目录散文件移入历史；367 个配置与日期产物文件字节/mtime未变。原件字节、权限、mtime逐个复核，artifacts旧链接仍解析。审计位于 /tmp/okr-main-workspace/archive-result.json，迁移索引在项目 archive/legacy-20261104/manifest.json。

### 实现与本机验收

- 持久 Main 索引、并发复用、复用既有专用团队、项目隔离和工具权限专项通过。集成用例走真实运行时/SQLite/tool handler：同一 Main 建团队、关联目标、计划任务、生成受管任务、写共享群聊、重新打开，保持同一身份；不调用真实模型或执行外部动作。
- 完整门禁中 Go 全量、Python 3421 passed/48 skipped、格式、类型、i18n、hover、构建和秘密扫描通过；随后补充边界的 16 个项目专项通过。最终提交钩子结果待补录。
- 前端 186 文件/1341 测试通过；最后相关文件与文件工作区 20 项专项通过。新增布局使用既有 tree chrome，关闭空预览释放宽度，文件页不自动聚焦搜索或唤起键盘。
- 真实桌面服务只读验收，以独立浏览器上下文按页读取构建资产；除了既有首页 Main 查询，所有写请求阻断。1280/1920/2560/3440 px、文件预览开关共八组，无文档横纵溢出；各目录入口可达。
- 真实宣传项目重开前后均读取 Main 5c1902b96d5c4fea83980354fbca0736，草稿保留。没有向 Main 发送验收指令、派活、上传或发布。
- 证据 /tmp/okr-main-workspace/desktop-qa.json、desktop-before.png、desktop-after-{1280,1920,2560,3440}.png、main-restored.png。索引哈希和访问记录均写入 JSON；临时浏览器上下文已关闭。旧素材兼容 URL 经生产 HTTP GET 返回 200，字节数与原 SHA256 一致，见 legacy-media-http-proof.json。

### 发布边界

本轮没有部署、重启生产 Go Agent/Python、修改 env/模型路由/费用/账目或强制解除 busy。持久 Main 的 schema19 仅用于开发验收；正式升级须在已有旧任务可信恢复后走受管安装流程。旧服务只复用已经核验的专用团队 Main，不把不支持的新目标绑定回退到首页。

用户此前要求不操作手机，真机仍未验收；桌面模拟不能代替真机触控。PR655 仍是前序草稿，不能把旧截图或旧门禁当作本轮手机通过。尚未增加同项目多 OKR 或自动日更调度器。

## 迭代：页面减法、群聊转交与消息隔离

持续验收 issue：[工作区与长期团队 #656](https://github.com/ybz21/Roami/issues/656)、[消息引用隔离 #658](https://github.com/ybz21/Roami/issues/658)。用户确认满意前保持开放。

### 产品设计与用户故事

一级导航收敛为 OKR、数据看板、团队活动、团队记忆和项目文件。移除复盘编辑与独立配置摘要；原文件和服务能力保留。文件入口打开项目根目录，记忆直接打开 memory 文件夹。目标页用 O → KR → 实施手段的语义列表导图展示真实关联；没有绑定 KR 的手段单列，不能虚构连线。看板只渲染 KR/指标趋势，不夹带数据录入、复盘和配置长表单。

团队页压缩为一行控制栏，动画与聊天共享剩余画布；成员职责放动画下方的紧凑列表，选中后才展开任务操作和依赖。群聊默认发给 Leader，定向线程明确继续原成员任务。历史回执保留在任务详情，不把投递或 executor 自述当验收。

首页对话工作区的消息、提醒、未读计数和已读动作按 conversation 隔离。全局通知中心可汇总来源，点击 OKR 通知先校验团队与项目的实际绑定，再进入该 OKR 固定 Main 并定位原 branch/message，不创建新实例、不修改首页绑定。历史分支只读，返回当前分支仍留在原项目。

### 技术设计

- 定向 swarm 消息先在事务内校验工作项、task/revision，再写带 task_id 的 post；拒绝不存在、跨团队和过期收件对象。幂等重放复用原 post/续派回执。
- Leader 使用既有 roami agent task steer 受管能力。TaskRevisions 在相同事务中为受绑定 Main 的续派写群聊记录，文本使用实际源用户授权的 executionText；群聊和成员线程可追踪同一次转交。此回执仍仅为接受处理。
- 通知列表与摘要增加 owner 验证的 conversationId 查询；工作区通过既有单对话已读接口确认，不使用全局全部已读。未升级服务返回未带作用域的摘要时不显示跨对话计数。
- 通知导航使用精确 conversationId 匹配团队，复核项目当前关联；节点切换、后续点击或离开页面后放弃旧异步结果。目标页再独立校验引用 conversationId 与真实团队 Main 相等，禁止把引用变成任意收信目标。
- 团队长期职责、任务修订与原生会话的持久恢复仍需继续实现。现有 task_steer 已保持 task/native branch，CLI 失效会话不能简单 fallback 到新会话。旧成员已被回收、新轮次仍在运行，不能直接迁移或回收当前实例。

### 本轮证据（开发中，未部署）

真实 CLI 群聊发给 Leader 的只读诊断有接受回执和实际 Main 回复：原 X/B站终端已被回收，重试继续绑定失效会话；没有以投递成功代替执行成功。证据 /tmp/okr-leader-workspace/leader-diagnose-receipt.json、leader-chat-evidence.json。

第一轮页面构建独立浏览器验收：1280/1920/2560/3440 均无文档溢出，动画画布高度456 CSS px，主要内容不再被上方关系卡片压住。源码资产按页从私有上下文读取，API只读；宿主监控插件 POST 被阻断，未派活或发送消息。上下文已关闭。证据 /tmp/okr-leader-workspace/desktop-qa.json、team-before.png、team-after-*.png、okr-after.png、data-after.png、files-after.png、memory-after.png。这些是第一轮快照，后续隔离代码仍需最终重验。

前一轮前端全量188文件/1343测试通过；此后追加了会话级通知隔离与回归，最终结果待补。CLI→Leader续派→同一成员/native branch→群聊记录的真实运行时/SQLite/注册CLI集成专项通过；当前Python专题61项通过。真实Android仍未操作，不能把窄屏模拟记作通过。

### 最终第一轮记录

第一轮提交 `9d410ee8`，提交门禁通过：Go 全量、Python **3427 passed / 48 skipped**（931.14秒）、ruff、typecheck、i18n、hover 与秘密扫描。前端全量 **188文件/1344测试**通过，构建通过。没有运行 full 命令或开新 PR，不能把该记录标为 PR 完整发布门禁。

真实浏览器最终第一轮：/tmp/okr-leader-workspace/final-qa/desktop-qa.json。四档无文档溢出；全局通知进入原宣传项目、原 Main 和原 branch/message，定位元素位于消息面板内，输入可用；没有创建或发送会话消息。所有临时 QA 上下文已关闭。窄屏模拟暴露团队/聊天分屏会使场景仅剩128px高，随后改为独立团队全屏预览，选成员返回原线程；最终几何与测试补录在后续提交。

[长期成员与执行轮次设计](long-lived-members.md)明确区分职责、实例和任务。当前 task/native branch 延续已有回归证明；独立职责实例、关闭终端后可信恢复以及历史重复职责迁移仍未完成，不把提示词约束当作宿主强制保证。

### 手机预览与摘要后续

前端全量最终 **188文件/1346测试**通过，typecheck、i18n（5150 keys）、hover 与构建通过。独立团队预览在392×766紧凑/粗指针模拟中占705px页面，动画高381.25px；聊天、预览、项目文件与Main均无文档溢出，没有自动聚焦输入。Main和团队两个页面均可返回原上下文，真实手机仍未验收。

证据 `/tmp/okr-leader-workspace/final-qa/phone-qa.json` 与 `phone-{chat,team,files,main}-emulated.png`；通知列表将Markdown链接显示为文件名并限制三行，点击仍回原消息。

后续边界：随后补充只读统一身份API，按owner/持久Main索引区分首页Main、项目Main和成员；未绑定Swarm也可导航到原项目Main。新运行时通过conversationIdentity能力标记启用，旧运行时保留团队绑定复验路径。该新增接口只有专项验证，不把旧生产环境的浏览器复验扩展宣称为新接口已部署。长期职责实体、未派发成员实例与原生会话可信恢复按独立设计继续实现。

### 统一实例身份补充

新增只读 GET /agent/conversations/:cid/identity 与 conversationIdentity 能力标记，Go代理路由同步接入。接口通过真实owner和持久索引识别首页Main、项目Main、成员或普通对话；冲突绑定拒绝，不产生对话、不重绑定实例。成员沿用native session的来源可见性校验。

通知导航和目标页均按该身份独立校验，未建团队的固定Main可进入原项目。新旧运行时通过能力标记区分，不能把不支持身份接口的旧服务当成可信身份响应。项目定义加载前不打开带默认草稿的Main面板。专项覆盖无团队Main、worker隔离、跨owner、首页/项目绑定冲突和跨项目共享，以及前端不新建/不发送的引用打开。

### 聚焦当前对话与真实实例

参考 Anthropic [Frontend Design](https://github.com/anthropics/skills/tree/main/skills/frontend-design) 的内容主导与减法原则，以及 Vercel [Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines) 的可访问、焦点与草稿保留要求；视觉仍服从本仓 UI 令牌和 Material 手机规范。

团队聊天只保留一个带标签的“当前对话”选择：群聊、Main、已派发成员。删除横排成员页签和输入区重复收件人；切换同步收信目标、消息过滤与已有提及，保留草稿及重试幂等键。未派发计划从成员列表查看，不伪装成已有对话。

动画仅呈现有证据的实例：CLI 对照共享活会话概览；原生执行器对照批量实例索引，并核对任务修订与 open 状态。关闭、过期或未派发的工作仍在列表和任务页，历史不删、不合并、不冒充活实例。场景不可见时暂停新增索引刷新，没有逐成员请求。

统一身份补充提交 `5d0a2a71` 的 quick 门禁已通过，包括 Python 全量、Go、前端静态检查。当前聚焦交互的专项通过；最终前端全量、构建、四档浏览器和 full 门禁另行记录。真实 Android 仍待用户解除此前不操作手机的约定。

### 2026-11-05 主线集成验收

整合 PR [#661](https://github.com/ybz21/Roami/pull/661) 包含前置 #655；继续跟踪 #656 / #658，未自动关闭。同步 #659 的页面记忆：保留项目/节点作用域及工作区导航，页签保存改为当前五入口；旧版 board/data 选择迁移到数据页，不恢复已移除的复盘入口。

- 前端全量 **189 文件 / 1363 测试**通过；typecheck、i18n、hover、build 通过。
- 初次 `check.sh full` 的 Go/Python/静态检查通过，Python **3433 passed / 48 skipped**，1200.93 秒；会话中断于最后构建。同一源码续跑构建、secret scan、staged policy 通过，产物哈希与此前验收一致。
- 主线冲突仅涉及前端；Python 源码树仍为 `7dd1b9d8f49f8c0dc6d6dda7ace94640a3df5413`。以已检查 PR head `d63a20b2` 为基准，增量 `check.sh full` 完整退出成功，Python 按可靠变更范围跳过；CI 仍按完整 PR 差异检查。
- 新构建的四档独立浏览器复验无文档溢出，动画仅 Main 与两个真实实例；数据页离开/重进恢复，当前对话切换、草稿保留、通知回原消息通过。记录 `/tmp/okr-leader-workspace/main-sync-qa/desktop-qa.json`；此前紧凑/粗指针模拟通过，Android 真机仍未操作。

截图采用演示文案，经 `pr-shot.sh` 存于 pr-shots，不进入主线。真实项目记录仅保留在登录保护的本机报告。生产运行时、环境、模型路由、费用、任务账目与 busy 均未修改。真实 Android 验收仍需解除用户此前不触手机的约定，不能将模拟当通过；长期成员实体和可信恢复仍未完成。

### 长期成员第一阶段

#661 已实际合入，全部CI通过。后续实现与隔离证据继续写在[长期成员与执行轮次](long-lived-members.md#第一阶段实现持久成员与轮次账本)。本阶段仅后端、CLI、协议与迁移，不改页面；手机、部署、生产运行时与原项目状态保持不动，不能以尚未授权手机为由阻断这些独立交付。

原生执行器恢复的后续设计与隔离验收见 [provider-recovery.md](provider-recovery.md)：保持原 provider 对话，按宿主与停止证明恢复物理终端。

未派发的 Roami 成员会话、首次派工复用及 Main 身份隔离见 [native-member-instances.md](native-member-instances.md)。

[从聊天开发文件化 OKR](file-dashboard-development.md)（2026-11-05）

## 2026-11-05：先看运行态，再看 Studio

[运行态交互原型](index.html) · [Studio 开发编辑原型](../20261104-okr-studio-project-ownership/index.html) · [技术实现](../20261104-okr-studio-project-ownership/implementation.html)。

本轮以用户最新要求为准：对话与协作同页，移除场景下重复职责列表；运行态保持简单，开发编辑从次要入口进入 Studio。原 index 说明保存在 revisions/20261105-before.html，历史实现/验收记录继续保留。原型数据、消息、模板应用与调度是本地模拟，不代表真实执行或已部署能力。完整产品设计、用户故事、模块/API、模板、Skill 日更和分批验收见技术方案 Markdown。
