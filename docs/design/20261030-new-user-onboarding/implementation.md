# 实现说明

2026-11-01。工作分支 `feat/new-user-onboarding` 已 rebase 到 `892fc9f3`（包含 PR #564 至 #576），四步为配置模型、配置智能体、创建项目、首个任务。最终门禁与前后对照见[合入前验收](merge-acceptance.md)。

## 产品行为

- 空节点登录后在首页展示起步清单：模型、智能体、项目、首个任务。已有模型连接、主模型配置或项目的用户继续使用原首页；设置中的「使用引导」始终可以重入。
- 第一步仅复用 ModelHub 添加连接和模型，服务端保存至少一个模型即完成。模型保存不会绑定主智能体或触发验证。
- 第二步先配置 Roami 主 / 后台模型，再接入执行器；模型目录共用 #564 的协议适配能力。应用后显式验证，验证失败保持第二步未完成。
- 智能体直接复用完整 `AgentCatalog`，Roami、Claude Code、Codex、OpenCode、Pi 默认全部可见。安装、登录终端、原厂 / 自定义模式、选模、额度和刷新间隔均与普通页面相同；`embedded` 仅改变详情的呈现容器。发现程序、登录状态、获取模型列表均不单独计作验证成功。
- 项目复用 `NewProjectModal` 的同一份字段、创建接口、目录选择和路径去重，本地目录及克隆仓库在两种容器中均可用。没有项目也能回首页聊天。
- 首个任务复用完整 `TaskComposer`，默认选已验证执行器，保留全部执行器及终端选项，外层提供可编辑的只读了解项目示例。用户明确提交后才创建会话并发送指令；成功回执结束起步清单，执行结果仍由实际任务视图展示。手机 Enter 换行，通过按钮提交。
- 「认识 Roami」覆盖首页、项目、能力、文件、浏览器、手机、设置，并解释首页任务 / 消息 / 记忆和能力八类。桌面两栏，手机为可返回的完整详情页。
- 未保存表单和任务使用现有内存草稿机制，页面间往返可恢复；刷新前提示未保存。API Key 不进入 URL 或浏览器持久存储。

## 路由与代码组织

引导使用 `#/onboarding` 及其子路由，而非原方案的查询参数。保留节点参数，嵌入原 AppShell、桌面标签、手机顶栏和四项底栏，不叠加第二套手机历史。

| 文件 / 模块 | 职责 |
| --- | --- |
| `components/onboarding/OnboardingHome.tsx`、`OnboardingChecklist.tsx` | 首页入口与起步清单 |
| `OnboardingPage.tsx`、`OnboardingProgress.tsx` | `model` / `agents[/kind[/models]]` / `project` / `task` 页面及步骤切换 |
| `ModuleGuide.tsx`、`guide-modules.ts`、`onboarding-route.ts` | `tour[/module]`、模块内容及手机标题和返回路径 |
| `onboarding-state.ts` | 按节点共享加载模型目录、主智能体配置、执行器、项目，组合完成条件；监听既有配置变更事件 |
| `OnboardingModels.tsx`、`OnboardingRoami.tsx`、`capabilities/ModelHub.tsx`、`RoamiAgentModels.tsx`、`AgentCatalog.tsx` | 第一步添加连接与模型；第二步配置主智能体与执行器，保持内联页面 |
| `projects/Projects.tsx`、`sessions/TaskComposer.tsx` | 复用项目创建及任务提交；引导使用内联表单 |
| `AppRoutes.tsx`、`AppShell.tsx`、`MobileNavigation.tsx`、`navigation.ts` | 懒加载页面、固定壳、手机导航归属 |
| `i18n/locales/{zh-CN,en-US}.ts` | 正式中英文文案，无原型私有翻译层 |

状态请求共用按节点缓存与进行中请求，15 秒超时，事件或重入时更新；不新增定时引导轮询。旧响应不能覆盖新节点。只有模型目录、主智能体配置、执行器和项目全部读取成功，才判断空安装。

`Preferences.onboarding[nodeID || 'local']` 仅保存 `started` / `dismissed` / `completed` / 选中项目 / 已提交会话。业务可用状态从服务端派生；偏好加载完成后才允许写入。隐藏清单不等于完成。

## 服务端验证

### 主模型

新增 `POST /agent/model-settings/verify`，Go 转发到 Agent runtime 的 `/v1/model-settings/verify`。`model_verification.py` 使用当前保存的主 / 后台 provider 各作一次无工具最小调用，相同路由复用一次结果；沿用 Go 模型网关和额度准入，不覆盖节点路由、参数或能力。

只有实际收到文本响应才成功；每个不同路由最长 45 秒。验证前撤销旧证明。验证记录原子写入私有 `agents/model-verification.json`，包含路由、参数、能力、上下文和凭据的摘要，不含密钥原文。`GET /agent/model-settings` 的 `verified` 只有全部指纹匹配才为真。变更配置或验证失败后，旧证明不能继续使用。

### 执行智能体

新增 `POST /agent/professional/:kind/verify`，`backend/api/agent-verification.go` 复用执行器的 `OneShotArgs`。当前已保存的本机配置生效，不额外打开自动权限、不指定另一套模型。

验证在专用空临时目录运行，要求仅返回 `ROAMI_READY`，不使用项目目录；60 秒超时，限制输出并清理本次进程组和临时目录。只有退出成功且输出包含独立的准确回复行才记成功，回显提示不算通过。同类验证不并发。

私有证明绑定程序身份、模型配置版本和对应 CLI 的认证文件，有效期 24 小时；配置、凭据或程序变化使旧证明失效。Claude 的启动计数不参与摘要，避免运行本身使证明失效。成功运行证明独立于额度面板缓存的登录推断，支持用户配置的 API 服务。普通发现 / 检查 / 升级响应附带 `verified`，引导和任务选择器使用同一事实。

## 验收边界

最新验收见 [PR #564 流程与验收](pr564-models-first.md)，使用隔离节点、本地模型响应及绝对路径指定的执行器夹具，未调用用户账号。初版曾因终端 PATH 继承遗漏实际调用本机 Codex，三个测试会话均已停止；该历史问题保留在[初版实现验收](implementation-acceptance.md)的隔离更正中。没有替用户安装 CLI；现有安装和账号终端继续由原有功能负责。

## PR #550 适配

本轮以 `b991fff8` 为基线恢复未提交实现，保留 #550 的 Roami 入口、安装状态、模型页原厂 / 自定义切换，以及旧设置 URL 的迁移。模型源和角色编辑使用 `#/onboarding/model/...`；手机标题和返回路径随子页变化，不叠加 `MobileSubPage`。来源草稿使用现有内存草稿机制，不持久化密钥。

模型网关在持久化目录时原子更新私有 `agents/model-catalog-revision`；它只包含每个模型实际路由和凭据的摘要，不复制目录或凭据原文。主模型及执行器验证只绑定各自使用的摘要；无关来源新增不要求重验，相关摘要在验证过程中变化则拒绝证明。这样更改上游密钥或地址时，即便回环 URL 与别名不变，也不能沿用旧验证。普通请求保留原超时，模型验证的代理响应头等待时间单独使用已有的 100 秒预算，覆盖两个不同角色各 45 秒的验证。

本轮详细检查与截图见 [PR #550 适配验收](pr550-rebase-acceptance.md)。

## PR #564 流程更新

第一步 `#/onboarding/model[/catalog/source/<id>]` 专注连接与模型，第二步 `#/onboarding/agents` 展示主智能体和执行器。`#/onboarding/agents/roami` 复用主 / 后台选模及显式验证。原本在第一步的主智能体逻辑迁到 `OnboardingRoami.tsx`；`onboarding-field-focus.ts` 复用手机字段避让，不另开滚动容器。

起步状态增加统一模型目录事实。下一步顺序为：无已保存模型则配置模型；缺少主智能体或执行器验证则配置智能体；然后创建项目并提交任务。手机的模型和智能体步骤均归属「工具」，返回栏随连接详情和 Roami 详情更新。完成与验证状态不由本地步骤勾选代替。

新检查和截图见 [PR #564 流程与验收](pr564-models-first.md)。前述 #550 记录保留为历史。

## 完整页面复用修正

按用户后续反馈移除引导专用功能裁剪：`AgentCatalog` 删除专用筛选和「其他智能体」开关，恢复额度与刷新间隔；`RoamiAgentModels` 保留高级配置；`ModelHub` 保留配置智能体动作；`NewProjectModal` 在两种容器中使用相同来源选项；`TaskComposer` 删除 `allowedAgents`，仅接受默认执行器和草稿标识。

各表单没有复制一份引导实现。`OnboardingPage` 持有步骤、说明、完成状态和路由衔接；共享组件的 `embedded` / `inline` 只负责避免第二层弹窗、顶栏及滚动区。详细验收见[完整页面复用](page-reuse.md)。
