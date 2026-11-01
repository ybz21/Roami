# PR #564 模型优先流程与验收

本记录为首次 PR #564 适配快照。后续按用户要求恢复完整既有页面，OpenCode、Pi 不再折叠，主模型高级配置、项目克隆和全部任务执行器均保留；最新行为及检查见[完整页面复用](page-reuse.md)。

2026-11-01。分支 `feat/new-user-onboarding` 已 rebase 到 `3b62f1f2944b4bff3d6c568e72117fa61c179081`，包含 [PR #564](https://github.com/ybz21/Roami/pull/564)。本轮按要求调整为「配置模型 → 配置智能体 → 创建项目 → 首个任务」。改动保留在工作区，尚未提交、推送或部署。

## 产品设计与用户故事

| 步骤 | 用户要做什么 | 完成依据 |
| --- | --- | --- |
| 配置模型 | 在同一表单添加连接、凭据和模型 | 服务端保存至少一个模型；空连接不算完成 |
| 配置智能体 | 先为 Roami 主 / 后台智能体选模，再接入 Claude Code、Codex 等执行器 | 主 / 后台模型验证成功，至少一个执行器验证成功 |
| 创建项目 | 选择节点上的已有目录，或创建新目录 | 项目接口成功返回真实项目 |
| 首个任务 | 编辑任务示例，选择已验证执行器并明确提交 | 实际会话创建成功；不把提交当作执行成功 |

刚安装的用户先解决模型来源，再选择谁使用模型，不需要在不同智能体下重复添加连接。主智能体和执行智能体共用 #564 的模型目录，由已有网关适配客户端协议；执行器仍可选择原厂账号。

第二步列表先展示带官方标志的 Roami，再展示 Claude Code、Codex，其他执行器可展开。第一步保存模型不会自动应用到角色，也不会发起验证调用。没有完成验证时可以稍后继续，首个任务页会列出需要补齐的条件。

首页、设置及模块介绍保持可达；能力介绍包含模型、智能体、Skills、MCP、CLI、工具、插件和市场，设置介绍按新顺序指向配置入口。旧 HTML 原型保留为设计快照，本轮流程以产品实现和本记录为准。

## 技术设计与上游适配

- rebase 前保存全部已跟踪和未跟踪改动到 stash `3ce68017d1a7db7260f06e1e0a5fa681bff22437`，更新后恢复并解决目录、模型表单和文案冲突，备份保留。
- `OnboardingModels` 仅嵌入 #564 的 `ModelHub`，保留连接与多个模型的原子保存、分组列表、用量和定价；来源及模型草稿共同恢复，凭据只留内存。
- `OnboardingRoami` 承接原有角色选择与显式验证，位于第二步。`RoamiAgentModels` 不再按旧的 Chat Completions 协议过滤共享目录。
- `onboarding-state.ts` 按节点共享模型目录、角色配置、执行器和项目事实。四类事实全部读取成功后才判断空安装；已有连接的升级用户不会被当作新用户打断。事件触发更新，不新增引导轮询。
- `OnboardingPage`、首页清单、手机标题和返回路径同步新顺序。模型与智能体步骤均归属手机「工具」。嵌入页只有全局返回栏和一个内容滚动容器；`onboarding-field-focus.ts` 负责键盘避让。
- 主模型验证、执行器验证与模型摘要失效机制沿用前轮实现；本轮没有绕过网关或改写节点模型路线。
- 截图复查发现列表复用时缺失能力公共样式，已由 `AgentCatalog` 直接导入其样式依赖；引导内覆盖容器高度和滚动，保留单一内容滚动区。修正后重新运行前端全套检查并复查截图。

## 自动检查

- `scripts/dev/quality/check.sh full` 通过：Go 全仓测试、CLI / Shell / 格式检查、Python ruff 及格式检查（543 文件）、Python **2847 passed / 47 skipped**、前端类型 / 翻译 / hover / 生产构建及文件策略检查。
- 前端独立全套检查通过：typecheck、i18n（4708 keys）、hover、**156 个 Vitest 文件 / 1151 项测试**、生产构建。
- 新增和更新用例覆盖模型优先状态、接口失败不误判新安装、共享请求及节点切换、连接与模型原子保存、草稿共同恢复且凭据不持久化、第二步 Roami 入口和所有协议的角色选模、修改选择后重新应用与验证。
- `git diff --check` 通过。日志：[完整质量检查](/api/file/tmp/onboarding-pr564-quality-full.log)、[前端测试](/api/file/tmp/onboarding-pr564-vitest.log)。

## 实际产品验收

专用隔离目录 `/tmp/roami-onboarding-pr564-00ac`，通过仓库隔离入口启动 HTTPS、Go API、Python runtime 和网关。使用私有 HOME、Codex / Claude / Pi / XDG 配置，启动命令明确指定测试 Codex 的绝对路径；主模型为本地 SSE 服务。本轮未调用用户原生智能体账号或外部模型服务。

桌面从空节点走通四步：

1. 首页显示新顺序。先只保存连接，模型数为零时第一步下一步禁用；随后在同一连接添加模型「共享起步模型」，即可进入智能体步骤，主模型仍未验证。
2. 第二步给 Roami 主 / 后台应用共享模型，最小调用验证成功；未验证执行器时仍不能完成该步。Codex 自定义模式选用同一连接和模型，原有协议限制没有隐藏它；调用测试程序完成执行器验证。
3. 通过真实项目表单登记测试目录。测试 HTTPS 证书最初导致请求失败，保留输入并接受专用测试主机证书后重试成功；没有修改产品逻辑规避错误。
4. 在真实 TaskComposer 编辑示例并提交。服务端保存项目、会话和本节点引导 `completed=true`，夹具记录 `task:/tmp/roami-onboarding-pr564-00ac/test-project`，另有独立临时目录的验证调用记录。

八个页面在 320 / 390 / 820 / 1100 / 1280 / 1600 / 1920 宽度下共 **56 个组合**通过：无文档滚动、横向溢出、缺失手机返回栏或底部动作越界。[布局断言](/api/file/tmp/onboarding-pr564-layout.json)。该布局检查不替代真机触控。

## Android 真机

Redmi Note 8，392 CSS px、DPR 2.75、coarse pointer，LAN HTTPS。实际触控由 `roami adb` 完成，CDP 用于读取页面和布局。

- 登录专用测试节点，从底栏设置进入「使用引导」，清单显示四步新顺序；进入配置模型时底栏选中「工具」。此时桌面已提交任务，因此手机属于完成后的重入场景，不记作第二次空安装。
- 点开连接与模型表单，只有一个返回栏和一个 `onboarding-scroll`。已保存密钥不回显，值为空。真实滑动、聚焦模型 ID，软键盘打开时字段保持可见，底栏隐藏。
- 收起键盘、返回模型列表，点下一步进入智能体列表。Roami 与执行器共同出现在第二步；点 Roami 管理后主 / 后台均显示共享模型，真实点开主模型下拉框可选择同一「共享起步模型」。页面无横向溢出，返回栏只有一个。
- 本轮手机验证覆盖上述入口、编辑、键盘和共享选模；完整项目创建与任务提交在桌面完成，没有在手机重复提交测试任务。

## 截图与 Review

- [首次首页 · 桌面](/api/file/tmp/onboarding-pr564-home-desktop.png)
- [第一步模型连接 · 桌面](/api/file/tmp/onboarding-pr564-models-desktop.png)
- [第二步智能体列表 · 桌面](/api/file/tmp/onboarding-pr564-agents-desktop.png)
- [Roami 主模型 · 桌面](/api/file/tmp/onboarding-pr564-roami-desktop.png)
- [Codex 共用模型 · 桌面](/api/file/tmp/onboarding-pr564-codex-shared-desktop.png)
- [首个任务 · 桌面](/api/file/tmp/onboarding-pr564-task-desktop.png)
- [能力模块介绍 · 桌面](/api/file/tmp/onboarding-pr564-modules-desktop.png)
- [第一步模型 · 手机](/api/file/tmp/onboarding-pr564-models-phone.png)
- [模型输入与软键盘 · 手机](/api/file/tmp/onboarding-pr564-model-keyboard-phone.png)
- [第二步智能体 · 手机](/api/file/tmp/onboarding-pr564-agents-phone.png)
- [执行智能体列表 · 手机](/api/file/tmp/onboarding-pr564-executors-phone.png)
- [Roami 共享选模 · 手机](/api/file/tmp/onboarding-pr564-shared-model-phone.png)

截图存于本机供 review，不提交一次性图片到主分支。

## 清理

已停止本轮专用 `ROAMI_HOME` 的服务进程，tmux 通过同一隔离目录的 `isolated-roami.sh --stop` 清理。仅关闭本任务桌面和手机测试页，移除专用 ADB 转发 `tcp:18866`，保留其他任务与用户现场。
