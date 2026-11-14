# 设计文档

各主题目录的入口和按日期排列的设计修订、验收记录。

| 主题 | 设计入口 | 本次迁入记录 |
| --- | --- | --- |
| 页面状态保留与统一仓库 | [20261113-文件工作区状态](20261113-文件工作区状态/README.md) | 主导航页面保留、后台活动暂停与桌面 / 真机验收 |
| 旧会话记录分批加载 | [20261113-transcript-paging](20261113-transcript-paging/README.md) | 最新 50 条首屏、向前游标分页、只读历史身份校验与桌面/真机验收 |
| 移除独立 DeepSeek Harness | [20261114-remove-deepseek-harness](20261114-remove-deepseek-harness/README.md) | 撤下执行器与适配，保留 API 模型和通用注册机制 |
| CLI 帮助统一 | [20261113-cli-help](20261113-cli-help/README.md) | 同一帮助结构、子命令参数与隔离回归 |
| DeepSeek Harness 与 Agent 注册（历史） | [20261112-deepseek-harness](20261112-deepseek-harness/README.md) | 主机统一列表、单次执行能力与桌面/真机验收 |
| 压缩状态反馈 | [20261112-compact-status](20261112-compact-status/README.md) | 状态行反馈、按需读取摘要与手机全屏详情，修复重复清空造成的闪烁 |
| 浏览器导航等待与卡死检测 | [20261112-browser-navigation-recovery](20261112-browser-navigation-recovery/README.md) | 慢导航保留连接、超时恢复、新标签回执与桌面/手机验收 |
| 首页委派任务与对话排版 | [20261112-home-delegated-activity](20261112-home-delegated-activity/README.md) | 委派工具步骤收在详情；正文阅读排版、紧凑输入区与整行任务导航 |
| 大模型用量、聚合与监控 | [20261112-model-usage-details](20261112-model-usage-details/README.md) | 概况 / 审计、源定价、九种路由策略与 24 小时滚动监控 |
| 派生任务提示词与 Main 回复 | [20261111-derived-task-prompts](20261111-derived-task-prompts/README.md) | Markdown 任务置顶、旧执行校验兼容与回复交付记录收拢 |
| 技能市场失败恢复 | [20261111-skill-market-recovery](20261111-skill-market-recovery/README.md) | 原请求重试、错误原因与桌面/手机验收 |
| 设置智能体入口整理 | [20261111-settings-agent-navigation](20261111-settings-agent-navigation/README.md) | 去掉旧模型入口、统一记忆迁入 Roami、旧链接兼容与桌面/真机验收 |
| 简洁返回按钮 | [20261111-back-navigation](20261111-back-navigation/README.md) | 统一左向 Chevron、无文字按钮、辅助技术名称与触控命中区 |
| 会话关闭首次点击反馈 | [20261111-session-close-feedback](20261111-session-close-feedback/README.md) | 检查状态即时反馈、等待请求去重、失败重试 |
| 热门技能与本机 Agent 安装 | [20261111-popular-skills](20261111-popular-skills/README.md) | skills.sh 热门榜、固定版本审核、本机与全部 Agent 安装 |
| 会话关闭阻塞 | [20261110-native-close-blockers](20261110-native-close-blockers/README.md) | 原生会话保留未知历史归档，分离 HEAD 工作区支持确认和清理 |
| Magpie 插件模型源 | [20261110-magpie-model-sources](20261110-magpie-model-sources/README.md) | WorkBuddy、豆包工作导入、隔离运行与网关 Key 管理 |
| 长期会话增量整理 | [20261109-incremental-context](20261109-incremental-context/README.md) | 复用有效摘要、保留完整来源与记忆版本校验 |
| OKR 发布后的动态取数 | [20261108-okr-publication-data](20261108-okr-publication-data/README.md) | 项目 SQLite 发布登记、稳定集合来源与 Main 确认边界 |
| 语音识别模型配置 | [20261107-speech-model-settings](20261107-speech-model-settings/README.md) | 能力中心入口、旧链接兼容与桌面/真机验收 |
| 任务创建与关闭异步化 | [20261108-async-task-lifecycle](20261108-async-task-lifecycle/README.md) | 持久受理、后台准备与清理、草稿恢复及桌面／手机实现验收 |
| 会话内存误杀与恢复 | [20261107-memory-scope-recovery](20261107-memory-scope-recovery/README.md) | 两次退出原因、原对话恢复与测试限额隔离回归 |
| 后台任务详情展示 | [20261106-task-detail-polish](20261106-task-detail-polish/README.md) | 结果优先、命令用途、窄栏溢出修复与桌面/真机验收 |
| 会话列表精简 | [20261105-session-list-metadata](20261105-session-list-metadata/README.md) | 侧栏只保留会话身份与状态，分支与目录集中到顶部查看 |
| Python 与 Skill 检查分流 | [20261105-python-check-scope](20261105-python-check-scope/README.md) | 完整 PR 范围、共享依赖回退与发布回归 |
| 会话同等展示 | [20261105-task-session-separation](20261105-task-session-separation/README.md) | 统一会话列表与聊天入口，关闭会话后任务独立留存 |
| OKR 固定主智能体与目录 | [20261104-okr-main-workspace](20261104-okr-main-workspace/README.md) | 持久负责人、目录归档与会话收拢 |
| 侧栏会话派生层级 | [20261104-sidebar-session-identity](20261104-sidebar-session-identity/README.md) | 项目下的父、子、孙会话导航 |
| Main 普通 CLI 参数与调用拒绝 | [20261105-main-cli-arguments](20261105-main-cli-arguments/README.md) | 普通参数、真实模型提醒闭环与桌面/真机验收 |
| OKR 活动场景与项目归属 | [20261104-okr-studio-project-ownership](20261104-okr-studio-project-ownership/README.md) | 历史场景、归属修复与分工验收 |
| 工作区围栏启动诊断 | [20261103-workspace-launch-diagnostics](20261103-workspace-launch-diagnostics/README.md) | 启动前拒绝、阻塞执行证据、历史频次与回归 |
| 蜂群 Main 编排与 Three.js | [20261103-swarm-main-three](20261103-swarm-main-three/README.md) | Roami Main、多执行器、三页签与受管验收 |
| 思考强度四档与对齐 | [20261102-thinking-levels](20261102-thinking-levels/README.md) | 竞品调研、四档提案与旧配置兼容 |
| 任务结果文件预览 | [20261102-task-file-preview](20261102-task-file-preview/README.md) | 独立预览页、手机全屏阅读与文件入口 |
| 公网首次加载诊断 | [20261102-initial-load](20261102-initial-load/README.md) | 公网响应传输、消息分页与数据库布局排查 |
| 大模型与智能体统一管理 | [20261030-智能体模型切换](20261030-智能体模型切换/README.md) | 多上游、聚合策略与能力入口第二版 |
| Roami Agent RSI | [20261022-roami-agent-rsi](20261022-roami-agent-rsi/README.md) | [42 条](20261022-roami-agent-rsi/records/README.md) |
| 对话体验优化 | [20261018-对话体验优化](20261018-对话体验优化/README.md) | [1 条](20261018-对话体验优化/records/README.md) |
| 对话输入交互 | [20261019-对话输入交互](20261019-对话输入交互/README.md) | [2 条](20261019-对话输入交互/records/README.md) |
| 执行器边界与路由 | [20261019-执行器边界与路由](20261019-执行器边界与路由/README.md) | [2 条](20261019-执行器边界与路由/records/README.md) |
| 派活回报 | [20261019-派活回报](20261019-派活回报/README.md) | [1 条](20261019-派活回报/records/README.md) |
| 记忆管理展示 | [20261019-记忆管理展示](20261019-记忆管理展示/README.md) | [2 条](20261019-记忆管理展示/records/README.md) |
| 会话刷新负载 | [20261020-会话刷新负载](20261020-会话刷新负载/README.md) | [1 条](20261020-会话刷新负载/records/README.md) |
| 前端应用拆分 | [20261020-前端应用拆分](20261020-前端应用拆分/README.md) | [1 条](20261020-前端应用拆分/records/README.md) |
| 主会话任务交接 | [20261021-主会话任务交接](20261021-主会话任务交接/README.md) | [1 条](20261021-主会话任务交接/records/README.md) |
| 任务进展与执行记录 | [20261021-任务进展与执行记录](20261021-任务进展与执行记录/README.md) | [1 条](20261021-任务进展与执行记录/records/README.md) |
| 浏览器标签管理 | [20261021-浏览器标签管理](20261021-浏览器标签管理/README.md) | [7 条](20261021-浏览器标签管理/records/README.md) |
| 能力中心 | [20261021-能力中心](20261021-能力中心/README.md) | [7 条](20261021-能力中心/records/README.md) |
| 专业任务常驻会话 | [20261022-专业任务常驻会话](20261022-专业任务常驻会话/README.md) | [4 条](20261022-专业任务常驻会话/records/README.md) |
| 任务会话与工作习惯 | [20261022-任务会话与工作习惯](20261022-任务会话与工作习惯/README.md) | [2 条](20261022-任务会话与工作习惯/records/README.md) |
| 运行时分发与安装 | [20261023-运行时分发与安装](20261023-运行时分发与安装/README.md) | [1 条](20261023-运行时分发与安装/records/README.md) |
| 手机文档预览 | [20261024-手机文档预览](20261024-手机文档预览/README.md) | [1 条](20261024-手机文档预览/records/README.md) |
| 本地模型代理与每日限额 | [20261026-本地模型代理与每日限额](20261026-本地模型代理与每日限额/README.md) | [2 条](20261026-本地模型代理与每日限额/records/README.md) |
| 设置分类 | [20261027-设置分类](20261027-设置分类/README.md) | [2 条](20261027-设置分类/records/README.md) |
| 关闭会话后的 worktree 清理 | [20261106-session-worktree-cleanup](20261106-session-worktree-cleanup/README.md) | 断连收尾、已关闭会话重试与 squash 恢复回归 |
| 关闭会话合入状态 | [20261112-worktree-merge-status](20261112-worktree-merge-status/README.md) | 关闭预检即时同步远端、离线本地状态刷新与隔离回归 |

## 其它主题

- [20261030-server-workspace-state](20261030-server-workspace-state/README.md)
- [20261030-new-user-onboarding · 新用户引导](20261030-new-user-onboarding/README.md)
- [20261030-OKR 每日行动](20261030-okr每日行动/README.md)：[Roami 宣传工作台](20261030-okr每日行动/promotion-workbench.html)、[交互形式设计书](20261030-okr每日行动/interaction-design.html)、[智能体动态构建原型](20261030-okr每日行动/prototype.html#/generate)、[每日实验闭环](20261030-okr每日行动/prototype.html#/cycle/creator)、[用户故事](20261030-okr每日行动/user-stories.html)、[产品调研与交互](20261030-okr每日行动/index.html)、[技术设计](20261030-okr每日行动/technical-design.html)。

- [20261030-对话文件链接](20261030-对话文件链接/README.md)

- [20261017-CLI统一设计](20261017-CLI统一设计/README.md)
- [20261017-agent框架设计](20261017-agent框架设计/README.md)
- [20261018-Agent机制对照](20261018-Agent机制对照/README.md)
- [20261018-agent委派验收](20261018-agent委派验收/README.md)
- [20261019-桌面智能体工作台](20261019-桌面智能体工作台/README.md)
- [20261020-任务主题与交付详情](20261020-任务主题与交付详情/README.md)
- [20261020-执行链路追踪](20261020-执行链路追踪/README.md)
- [20261021-主会话上下文与检索恢复](20261021-主会话上下文与检索恢复/README.md)
- [20261021-会话CLI隔离](20261021-会话CLI隔离/README.md)
- [20261021-查询任务导航失败恢复](20261021-查询任务导航失败恢复/README.md)
- [cluster](cluster/)
- [p2p](p2p/)
- [phone](phone/)
- [plugin](plugin/README.md)
- [reliability](reliability/)
- [settings](settings/index.html)
- [swarm](swarm/)
- [web](web/README.md)

[本次规则精简与迁移校验](20261028-agent-instructions/README.md)

- [20261103-project-okr · 真实项目 OKR 工作台](20261103-project-okr/README.md)：项目入口、真实指标、Swarm 关联和验收记录。

- [团队一键暂停与恢复](20261113-team-work-pause/README.md)
