# OKR 活动场景与项目归属

2026-11-04。续接 [旧蜂群历史恢复](../20261103-project-okr/legacy-recovery.html)；本分支基于 `fix/okr-legacy-history`（PR #648）。

[产品、用户故事与技术方案（HTML）](index.html)

## 分工

本分支只处理具体活动的 Three.js 场景与宣传会话项目归属。恢复的“目标到每日行动”主会话负责 `.roami/okr` 文件包、看板与 connector、智能体配置、团队记忆、执行闭环、旧成员验收回收，以及最终集成与 PR。各自主线不互改。

## 实现

- 旧团队复用 `SwarmStudio`，提供协作、群聊、看板；场景节点保持 idle，只做 15 FPS 的待机转头，关闭动画、减少动态效果、后台及隐藏标签均停止渲染。历史状态保持原记录，不转成正在执行或验收成功。
- `SwarmStudio.active` 在离开协作页时释放 WebGL 资源，返回后恢复选择；WebGL 失败仍可查看记录并重试。
- 已登记的普通项目与稳定 session 台账共同确定归属，修复启动目录被错误钉到源码 worktree 的运行时缓存。只接受同一稳定会话及 tmux ID，保留 Git 项目的既有 worktree 绑定，不改变进程目录。
- 前端按已保存 home 认领所有普通项目会话，避免依赖截断的 top 列表；新归属优先于旧 worktree 快照。受管团队的显式 projectId 优先于 directory。

## 验收

- `scripts/dev/isolated-roami.sh /tmp/okr-activity-acceptance scripts/dev/quality/check.sh full` 通过；Go 全量、i18n、hover、typecheck、生产构建与扫描通过。没有 Python 改动，门禁按范围跳过 Python。
- 前端全量：183 文件 / 1,286 测试通过；`go test -race ./backend/worktree` 通过。
- 桌面 1280 / 1920 / 2560 / 3440 CSS px，目标对话展开与收起共 8 组；文档无横/纵溢出，场景有正面积并在页面边界内。截图分别为 `final-*.png` 与 `final-chat-*.png`。
- 动画开时两帧场景像素有 17,241 个变化；关闭后两帧变化为 0；进入群聊 canvas 数为 0，返回后恢复选择。证据 `animation-proof.json`、`final-hidden-scene.json`、`final-scene-selection.json`。
- 隔离创建宣传/源码各一个活会话，故意把宣传运行时 home 指向源码 worktree 后启动真实 Go 服务。`/sessions/annotations` 与 `/projects` 都归回宣传项目，源码会话保留原 worktree，持久 home 不变。证据 `ownership-proof.json`。没有重启已回收的旧六名成员。
- Redmi Note 8 经 LAN HTTPS，392×766、compact/coarse：ADB 真点三页签；协作页真滑动 308px 后，第二成员中心命中并点开（details 状态为 false/true/false/false）；看板真滑动 285.09px；上下栏保留、文档无横溢出。最终核对入口脚本 `index-BxJBwEG6.js`，避免同地址旧标签与缓存包混入验收。证据 `phone-final-state.json`、`phone-members-scrolled.json`、`phone-member-detail.json`、`phone-board-scrolled.json`。

一次性截图与完整日志保存在 `/tmp/okr-activity-acceptance/`；桌面改前 `desktop-before.png`、改后 `desktop-final.png`，手机改前 `phone-before.png`、改后 `phone-final.png`、详情 `phone-member-detail.png`，由集成主会话随最终 PR 上传 `pr-shots`，不提交进主分支。

测试 HTTP 服务与独立 tmux 在交接前停止；只回收本次两个测试会话。手机旋转恢复原值 1、9567 转发移除；本任务浏览器标签关闭。

本次不部署、不重启线上服务、不修改线上原始业务数据；真实部署与整体 OKR 验收由主会话统筹。

## 2026-11-05：运行态与开发 Studio 原型

按用户要求，先看[最终运行态](../20261104-okr-main-workspace/index.html)，再看[Studio](index.html)，最后看[技术实现 HTML](implementation.html) / [完整方案](implementation.md)。

本轮将“团队活动场景”和“开发 Studio”明确区分。前者在运行态与聊天同页，移除下方重复成员长表；后者以对话、模板、运行预览和草稿应用开发同一个 OKR。项目归属与原实例保持是两种状态共同的底层约束。旧 index 保存在 revisions/20261105-before.html，不删除历史归属修复证据。

预置[模板样例](templates/README.md)含内容增长、产品交付、运营指标，明确无凭证/实例 ID/模拟观测，调度默认关闭。它们是设计种子，模板装配与通用 Skill 日更尚未实现。本轮不部署原型、不修改真实项目和团队、不触碰手机。

[本轮原型验收](acceptance.md)。

补充：Connector 位于 connectors/ 的 Skill 包；[用户 HTML 读取数据的可运行样例](dashboard-example.html)，以及[生成/编辑 Skill 扩展示例](templates/okr-development/SKILL.md)。数据保存、读取 API、组件与模板规范均见技术方案。

## 2026-11-06：先设计 SQLite 与团队通信

[交互式设计稿](data-and-swarm.html) · [SQLite、读取层与模板](sqlite-data-design.md) · [Swarm 通信与 Main 收件箱](../20261104-okr-main-workspace/swarm-communication-design.md)。

本轮为设计提案。未评审的 SQLite 实现草稿已移出工作区；真实项目没有建立本提案的数据库、改变存储权威或启用新增通信协议。

[数据与团队设计稿检查](data-team-design-acceptance.md)：仅文档与模拟交互，非新增底层机制验收。

通信重点：[逐跳与多个 OKR 演示](../20261104-okr-main-workspace/communication-engine.html)。实现前补充 [SQLite v1 契约](sqlite-v1-contract.md) 与 [协调回合契约](../20261104-okr-main-workspace/swarm-delivery-contract.md)。

SQLite 采集层的 [源库实施与验收范围](sqlite-source-store.md) 单独记录通用脚本、版本与恢复；不代表宿主确认存储迁移或完整自动循环已经完成。


## 通用看板层级与宣传实例（2026-11-11）

本轮需求合并到[原技术方案](implementation.md#看板分层的通用框架契约)和[原运行态文档](../20261104-okr-main-workspace/README.md#看板的分级与分层)：框架支持项目定义的分组、嵌套与叶子视图；[宣传工作量原型](../20261104-okr-main-workspace/workload-dashboard.html)仅是项目示例。通用导航不得写死X/B站、三个Tab或运营角色。当前原型与新增框架设计的实现/验收状态分开记录。

## 2026-11-12：项目内创建与搭建

[创建、聊天搭建与运行设计](project-creation-flow.md) · [可点击原型](project-creation-flow.html)。OKR 归入项目 Tab，角色与 Agent 分开配置，构建确认后显式运行；此稿取代旧的独立导航入口提案，历史验收保留。当前为设计，不恢复已停止项目。
