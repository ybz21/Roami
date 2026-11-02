# 完整页面复用

2026-11-01。根据用户反馈，引导应在原有页面外增加步骤和说明，不能另做功能较少的新手页面。本轮基于包含 PR #564 的工作区继续修改，尚未提交、推送或部署。

## 产品设计

流程仍为「模型 → 智能体 → 项目 → 首个任务」。页面内容由现有组件直接渲染；引导外层提供进度、简短说明、返回、继续和完成状态。

| 页面 | 共用组件 | 完整保留的操作 |
| --- | --- | --- |
| 模型 | `ModelHub` | 连接与模型表单、模型 / 用量 / 定价、配置智能体入口 |
| 智能体列表与执行器详情 | `AgentCatalog`、`AgentModels` | Roami、Claude Code、Codex、OpenCode、Pi，搜索、安装、升级、账号终端、模型、额度、刷新间隔 |
| Roami 模型 | `RoamiAgentModels` | 主 / 后台选模、应用、恢复、模型能力与上下文高级配置 |
| 新建项目 | `NewProjectModal` | 本地目录、克隆仓库、目录选择、项目名称，同一创建逻辑 |
| 首个任务 | `TaskComposer` | 全部执行器及终端选项、附件、项目 / Git 选项和提交逻辑 |

引导可默认选择已验证执行器，不能因此隐藏其他选择。模块介绍继续作为额外的可选阅读入口。

## 用户故事

- 用户准备使用 Pi 或 OpenCode 时，在引导中直接看到与能力页相同的卡片，进入相同的管理和模型配置。
- 用户需要高级模型参数时，展开与普通 Roami 配置页相同的「模型能力与上下文」。
- 用户从远端仓库起步时，直接使用原有克隆入口，不必退出引导才能创建项目。
- 用户在任务中更换执行器时，保留完整选择和已经输入的任务内容。

## 技术设计

`OnboardingPage` 只组合共享组件、步骤状态、说明和路由回调。`OnboardingModels`、`OnboardingRoami` 包住现有表单，后者附加显式验证及完成反馈，没有复制字段或选模、应用逻辑。

`AgentCatalog` 删除业务性的 `onboarding` 模式及额外筛选，`embedded` 仅决定详情放在引导内容区还是原有弹窗 / 手机子页。安装、授权、模型和额度使用同一实现；不再隐藏 Pi、OpenCode、额度或刷新间隔。

`ModelHub.embedded`、`RoamiAgentModels.inline`、`NewProjectModal.inline` 只调整呈现容器和引导草稿衔接；功能不因此裁剪。嵌入详情避免第二个手机返回栏和嵌套滚动区。

`NewProjectModal` 两种容器共用相同来源选项和 `ok` 提交函数，删除引导专用的目录存在性检查。`TaskComposer` 删除 `allowedAgents`；`initialAgent` 仅设初值，`draftKey` 仅控制草稿与键盘避让，不影响可选项和提交权限。

## 自动检查

前端 typecheck、i18n（4705 keys）、hover、157 个 Vitest 文件 / 1154 项测试、生产构建全部通过。

回归测试覆盖完整五项智能体目录及原有额度 / 刷新设置、手机内联详情无第二层返回栏、主模型高级配置可达、普通及内联项目表单都提交相同克隆参数、首个任务默认执行器及完整选项切换时保留输入。

本轮仅修改前端和设计文档，沿用上一轮 Go / Python 验证结果；没有重新执行无关的后端检查。

- [前端测试日志](/api/file/tmp/onboarding-reuse-vitest.log)
- [生产构建日志](/api/file/tmp/onboarding-reuse-build.log)

## 浏览器与 Android 验收

使用 `/tmp/roami-onboarding-pr564-00ac` 专用隔离节点、私有 HOME 与测试配置，未安装或调用实际执行智能体，未向外部模型或 Git 服务发送业务请求。

桌面在实际产品中切换普通 `capabilities/agents` 与引导 `onboarding/agents`，对比五项卡片身份、操作及刷新设置，结果完全相同。[页面一致性断言](/api/file/tmp/onboarding-reuse-catalog-parity.json)。

九页（模型、智能体、Roami、OpenCode 详情 / 模型、Pi 详情 / 模型、项目、任务）在 320 / 390 / 820 / 1100 / 1280 / 1600 / 1920 下共 63 个组合通过，无横向溢出、文档滚动、缺失手机顶栏或页脚越界；每个宽度均断言智能体五项完整展示。[布局断言](/api/file/tmp/onboarding-reuse-layout.json)。

Redmi Note 8、392 CSS px、coarse、LAN HTTPS，实际 `roami adb` 点按及滑动，CDP 仅用于读取状态：

- 列表默认包含 Roami、Claude Code、Codex、OpenCode、Pi，并保留额度、刷新间隔；实际滑动查看底部，没有嵌套滚动区。
- 分别点开 Pi、OpenCode 管理，再进入各自模型页，原厂 / 自定义及高级恢复入口可达；返回使用现有全局返回栏，没有第二层顶栏。
- 进入 Roami，真实点开「模型能力与上下文」，渲染同一高级表单；仍只有一个滚动区、一个顶栏，无文档和横向溢出。
- 项目页真实切换到「克隆仓库」，URL、目录、名称等原有字段出现。本轮未执行实际克隆或任务提交；两种容器的克隆请求参数和任务选择通过组件测试检查。

## 截图

- [智能体列表 · 桌面](/api/file/tmp/onboarding-reuse-agents-desktop.png)
- [OpenCode、Pi 及刷新设置 · 桌面](/api/file/tmp/onboarding-reuse-all-agents-desktop.png)
- [Pi 及刷新设置 · 手机](/api/file/tmp/onboarding-reuse-all-agents-phone.png)
- [Pi 模型页 · 手机](/api/file/tmp/onboarding-reuse-pi-models-phone.png)
- [OpenCode 管理 · 手机](/api/file/tmp/onboarding-reuse-opencode-detail-phone.png)
- [OpenCode 模型页 · 手机](/api/file/tmp/onboarding-reuse-opencode-models-phone.png)
- [Roami 高级配置 · 手机](/api/file/tmp/onboarding-reuse-advanced-phone.png)
- [项目克隆 · 手机](/api/file/tmp/onboarding-reuse-project-clone-phone.png)

图片为本机 review 产物，不提交主分支。

## 清理

已停止本任务专用服务进程，使用同一隔离入口 `isolated-roami.sh --stop` 清理测试 tmux；关闭本任务桌面及手机测试页、移除专用 ADB 转发。未操作其他会话、页面和用户配置。

## 欢迎区精简（2026-11-01）

按截图反馈移除标题上方的机器人装饰图标及其留白，四步清单与操作继续复用原组件。基于 `eae0ac74`，仅修改欢迎区 JSX 和对应无用样式；前端 typecheck、i18n、hover、1154 项测试和生产构建通过。Android 真机确认内容从标题开始、无独立装饰图标，四项清单完整、无横向溢出，只有一层顶栏。

[桌面效果](/api/file/tmp/onboarding-welcome-no-icon-desktop.png) · [手机效果](/api/file/tmp/onboarding-welcome-no-icon-phone.png)。截图采集于本地验收，未部署。

## 桌面起步页精简（2026-11-01）

标题缩短为「设置 Roami」，删除重复介绍四步顺序的说明。使用统一 `.tt-pagehead`，桌面标题与开始设置、模块介绍、稍后操作同排；次要操作使用文字按钮。上下留白和清单间距收紧，手机自动堆叠标题与按钮，并保留触控高度。

前端 typecheck、i18n（4704 keys）、hover、1154 项测试和生产构建通过。中英文各 7 个宽度共 14 组检查通过：无横向溢出或文档滚动，四项清单完整，桌面标题与主操作同排。Redmi Note 8 实际点通模块介绍、返回与开始设置，只有一层顶栏。

[桌面效果](/api/file/tmp/onboarding-compact-desktop.png) · [手机效果](/api/file/tmp/onboarding-compact-phone.png) · [布局证据](/api/file/tmp/onboarding-compact-layout.json)。截图采集于本地验收，未部署。

合入前同步至 `5d66fbe8`（PR #579），模型源编辑及批量拉取沿用上游组件，本次只调整起步页。同步备份为 stash `f90756f0a73af12383154ae6459932c93254ea19`；合入检查见对应 PR。
