# 设计稿验收 · 2026-11-16

范围：仅 HTML 设计文档与页面内演示。未实现产品模型能力、CLI 选模或 Auto 调度；未调用真实模型生成，未修改生产模型、账号、密钥、额度或路由。桌面使用本任务专用 Roami Chrome 标签页，手机使用 Redmi Note 8 的 Chrome 真机。

## 跨会话统一（最新）

- 只读核对“本机网关设计”会话 `2026-1112-1808-jl57`、分支 `feat/local-gateway-workspace` 的 `21ca98ec`，与本会话 `58c750ac` 对照。读取了网关设计、复核、实现说明和源代码；对方工作区没有被修改。
- 两个检查点执行 `git merge-tree --write-tree 58c750ac 21ca98ec` 成功，无冲突；这是预演，未实际合并分支。网关分支包含生产代码，本 PR 仍只有设计资料。
- 网关、Roami 选择器、调用示例和任务改用同一原型目录。保留接入 / 目录双入口、统一卡片、成员 / 权重与桌面检查器；三类范围明确为已接入 / 聚合 / 上游目录。上游自动路由和原生 / 适配能力另列。
- 四档桌面 1280/1920/2560/3440 均检查模型左侧导航、网关双页签、三类卡片、检查器开关释放空间与横向溢出。真实安全上下文复制调用名称成功，卡片选择的调用 ID 与示例一致。
- 共享数据验收：备用源目录模型启用后，Roami 选择器立即能找到同一模型；Free pool 初始三个成员中有两个图片成员，删除其中一个后，任务图片候选变成一个，而非扫描全部目录里的三个图片模型。严格验证条件仍进入等待。
- Key 名称校验、创建、一次性复制、重命名、启停、轮换、固定单例和替换确认通过；明文关闭后从 DOM 和原型状态清除，跨业务页保留的只是 Key 元数据。
- Redmi Note 8 经任务自签 HTTPS 预览，局部接受本测试站点证书后验证：网关页签、全屏成员详情、启用来源、共享选模、成员限定 Auto，以及新 Key 的实际剪贴板写入。没有修改全局浏览器安全设置。
- 修复手机键盘焦点变化导致首次提交可能落空：沿用项目的 VirtualKeyboard overlaysContent、布局 keyboard token 和提交按钮保留输入焦点；最终真实触控一次点按提交通过。桌面与手机没有 JavaScript 异常，未发起 `/api/` 或模型生成请求。
- 最终原始数据见 `acceptance.json.unifiedDesign`；验收脚本为 `/tmp/roami-model-capability-design/verify-unified.mjs`。一轮过程中本地静态服务退出，保留已有截图后重启隔离服务，最终完整检查通过；不将这次测试服务退出归因于产品代码。
- 本轮技术设计增加统一章节，原型统一管理与消费流程；仍只交付技术设计、原型设计两个 HTML。此前“技术设计不变”仅对应上一轮页面位置修订。

## 页面位置修订（历史）

- 默认进入 `#/capabilities/agents/roami`，对应截图里的“Roami 主智能体与执行智能体”。实际入口通过 `CapabilitiesPage.tsx`、`AgentCatalog.tsx`、`RoamiAgentModels.tsx` 核对：能力 / 智能体 / Roami；手机经工具 / 能力进入。此前把此页口述为设置入口不准确，当前原型和 README 已纠正。
- 原型采用 Roami 导航、能力分类、页面位置提示和两个模型选择框；只有点开选择框才出现共享能力选择器。首页对话、项目下任务、模型目录各有独立路由，不再把三个演示堆在一页。目录位于能力 / 大模型 / 本机网关。
- 桌面 1280/1920/2560/3440 均验证弹层边界、源页面位置、筛选、选择应用和容器溢出。初始九项（八个附件模型与聚合示例），图片条件五项，叠加具体模型类型三项。
- Roami 修改应用、返回智能体列表再进入保留页面内选择；首页对话与任务覆盖不改模型默认设置。任务 Auto 图片筛选得到三个声明候选，要求已验证后进入等待；没有实际创建任务或调用模型。
- Redmi Note 8 真机验证四项底部导航、经工具 / 能力 / Roami 的真实触控路径、全屏模型页、图片筛选、选择应用、返回、对话选模与任务 Auto。无 JavaScript 异常，无内容区横向溢出。弹层通过原生 dialog 管理焦点与 Escape，手机仅保留一个返回栏。
- 原始测量保存在 `acceptance.json.contextualPrototype`，脚本 `/tmp/roami-model-capability-design/verify-context.mjs`。技术设计 HTML 与修订前逐字节相同；仅原型和支撑资料发生变化。

## 双文档修订（历史）

- 对外交付仅两份：[技术设计](technical-design.html)、[原型设计](prototype.html)，顶部只保留两个入口。`index.html` 为原型旧入口别名，不作为第三份文档。
- 技术设计承载能力数据、标准字段、模块/API、CLI、调度规则、长时任务与验收边界；原型仅承载能力目录、Roami 选择和 Auto 交互。
- 重新通过桌面 1280/1920/2560/3440：两个入口真实点击切换、内容隔离、目录详情开关与空间回收、容器无横向溢出。图片筛选、Main/Worker 选择器、Auto 验证不足空池及主题切换通过。
- Redmi Note 8 真机通过两个页面的真实触控切换、筛选、全屏详情、返回保留筛选与手势滚动；技术页和原型页均无内容容器横向溢出。无 JavaScript 异常。
- 原始测量保存在 `acceptance.json` 的 `twoDocuments`，临时脚本为 `/tmp/roami-model-capability-design/verify-split.mjs`。本次修改仍限于设计资料。

下方保留首次合稿的内容核对与历史验收；最新布局以双文档修订为准。

## 内容核对

- 对照现有 `CatalogModel`、源模型详情、角色绑定、CLI 帮助、执行 spec 与 Python native 任务校验，区分现有基础和拟新增契约。
- 通过公开 Models API 逐项匹配附件中的六个 OpenRouter ID；原始字段子集、抓取时间与响应摘要保存在 [model-evidence.json](model-evidence.json)。这些是上游声明，尚未验证本节点链路。
- 其中五项为具体模型，`openrouter/free` 为上游自动路由。五个具体模型中三项声明图片输入；计入路由共四项。两个本地名称保留未知，不根据名称断言聚合、图片或免费能力。
- 附件原件与设计输入副本 SHA-256 相同：`352a8d6f380f0e7d690165b38617c4be7ca788c114ce8bc7a1c1f5afe016464e`。
- 新增命令、JSON 字段和错误码在文档中明确标记为提案。开发者文档使用中文，符合仓库 i18n 的文档例外；未增加产品硬编码文案。

## 浏览器与真机

测量明细见 [acceptance.json](acceptance.json)。交互通过 CDP 的真实鼠标/触摸输入并核对 `elementFromPoint`；没有以 DOM `click()` 代替命中测试。

| 桌面 CSS 宽度 | 详情关闭时目录宽度 | 详情打开时目录宽度 | 验收 |
| --- | ---: | ---: | --- |
| 1280 | 1001 | 641 | 文档无横向溢出；关闭释放 360px |
| 1920 | 1641 | 1281 | 同上 |
| 2560 | 2281 | 1921 | 同上 |
| 3440 | 3161 | 2801 | 同上 |

- 桌面内容容器高 940px（1000px 视口减真实 60px 页头）；文档本身不滚动，`main` 承担纵向滚动。深浅主题均打开检查。
- 图片筛选得到四项，叠加具体模型类型得到三项；添加音频条件为空态。详情可打开、关闭，宽度完全归还。
- Roami 选模复用全部演示能力条件；图片条件下包含四个公开条目与一个按请求筛选成员的聚合示例。聚合类型筛选仅留下该池。Main/Worker 切换保留各自页面内选择。
- Auto 图片与工具条件得到三个声明候选；要求已验证后为空池，模拟额度耗尽后显示等待且不转付费。未将未知验证、真实延迟或余额伪造为通过。
- Redmi Note 8：约 393 CSS px，`compact/coarse`。实际触控完成图片筛选、全屏详情、返回保留筛选、Roami 选择与 Auto 计划。详情覆盖全部可用视口；真实滚动使 `main.scrollTop` 从约 6295 增至约 6644。
- 最后一轮同时检查 `document` 和 `main` 的横向边界。修正了技术表格的 grid 最小宽度造成的内部横向溢出，并让 checkbox 保持 16px 视觉尺寸、由 44px label 提供触控区域。
- 桌面与手机运行无 JavaScript 异常。本稿为独立开发者文档，产品顶栏、四项底栏、软键盘与安全区的完整业务验收列为未来产品实现的门禁，不冒称本次已实现或验收。

## 检查与交付

- `node docs/design/20261114-model-orchestration/history/20261116-model-capabilities/build.mjs` 成功，HTML 内嵌 JS/CSS，无 CDN 依赖；源码复用现有 `useLayout()`、图标和令牌。
- `scripts/dev/quality/check.sh quick` 通过，包括 CLI 审计、shell 语法、Go 格式、i18n、hover、前端 typecheck、secret scan 与 staged policy。
- 本次仅修改 `docs/design/**`。Python/Go 运行测试按质量脚本范围跳过；没有产品 frontend 改动，不运行无关的全量 Vitest 或生产构建。
- `git diff --check` 通过。原图与 JSON 相对资源保持在同目录，截图只放本机验收目录及 PR 的 `pr-shots` 分支，不提交到主分支。

本机验收目录：`/tmp/roami-model-capability-design/`，含 browser-verification.log、verification.json、quality-quick.log 与桌面/手机截图；一次性验收脚本为该目录的 `verify.mjs`。静态服务通过仓库隔离入口启动，收尾通过同入口 `--stop` 核对并清理测试服务器。
