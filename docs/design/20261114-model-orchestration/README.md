# 模型源与聚合：工作台重构

2026-11-20 [调度与排查原型（HTML）](gateway-prototype.html?v=workbench-20261120#/workbench) · [最新图解设计（HTML）](latest-design.html) · [当前设计（HTML）](model-monitoring-and-aggregation.html) · [历史设计与验收（HTML）](history/index.html)。

新增「调度与排查」首屏。左侧显示当前聚合的可调度顺位和冷却时间，右侧按请求结果筛选，并在同页查看选中请求的尝试。由结果定位到完整审计、限流来源或聚合配置。七个管理入口可从工作台或「模型管理」打开。

在同一原型补充[策略与承载观测](gateway-prototype.html?v=pool-observation-20261120#/workbench?view=strategy)，参考本机 LLM Gateway 的策略预览、成员计数和来源健康。桌面和 Redmi Note 8 验证按顺序、轮流、3:1 权重、模拟排除首选、按时段更新成员统计、单来源无跨源备用和缺样本状态。生效顺位读取已保存的演示配置，统计读取演示请求记录。

桌面四档宽度与 Redmi Note 8 真机通过聚合切换、有请求与空状态、失败筛选、HTTP 200 中断、审计返回和来源跳转。桌面验证了在原聚合页重排并保存后，工作台首选同步更新。首屏使用离线合成数据。改前改后见 [PR #989](https://github.com/ybz21/Roami/pull/989)。

2026-11-20 [排查工作台改版](latest-design.html#workspace-ux)。聚合把首选、备选及来源摆在首屏，调度模拟按需展开。监控并列趋势和结果分布，独立清除时段或结果筛选。审计先显示请求结论，再按顺序显示上游尝试、状态和原因。沿用 UI/UX Pro Max 的图表与触控指引、Impeccable 的层级评审、Vercel Web Design Guidelines 的控件标签和焦点规则。

桌面 1280、1920、2560、3440 CSS px 和 Redmi Note 8 验证展开调度模拟、趋势与结果联合筛选、进入审计再回到原请求焦点。离线打开统一原型，核对来源顺位、切换恢复筛选和请求时间线。改前改后见 [PR #989](https://github.com/ybz21/Roami/pull/989)。

以部署版 `okr-settled-coordination-012a0761` 的七个入口为基准，通过 `roami chrome` 打开列表和详情，对照字段、操作和返回路径。统一原型直接加载本分支的 `ModelHub` 及其子页面。页面标签、业务控件、表格和布局随正式组件更新。

原型的入口在 [entry.tsx](gateway-prototype/entry.tsx)，假目录、计费和调度记录由 [fixture.ts](gateway-prototype/fixture.ts) 与 [activity-fixture.ts](gateway-prototype/activity-fixture.ts) 提供。运行 `node docs/design/20261114-model-orchestration/gateway-prototype/build.mjs` 生成一个自包含 HTML。演示操作写入当前页内存，刷新恢复样本。WorkBuddy 签到页和请求故障用例可从设计总览直接打开。

本轮在 Chrome 文件页、Roami 文件接口和 Redmi Note 8 真机打开统一原型。桌面 1280、1920、2560、3440 CSS px 核对工作区宽度。桌面和手机均点通连接定价、插件版本、聚合成员、额度与逐笔审计、模型源抽检、按结果筛选并返回、网关目录和语音配置。四个请求故障用例与 WorkBuddy 签到使用合成数据。检查 38 个 HTML 的 581 条本地引用，修复归档中的两条返回链接。浏览器截图见 [PR #989](https://github.com/ybz21/Roami/pull/989)。

排查工作台实现。聚合编辑页顶部展示生效顺位、近一小时失败率和切换次数。监控默认展示请求终态，来源比较保留上游尝试与抽检。点时段后固定范围，返回时保留条件。请求审计展示已发出的尝试与终态，关联号放进技术详情。

隔离网关用四次实际请求验证了零尝试 503、尝试后耗尽、首选 429 后恢复和 HTTP 200 流式中断。请求统计共四次、最终失败三次、切换恢复一次。桌面四档和 Redmi Note 8 验证从聚合和监控进入审计，以及原聚合和筛选可恢复。截图见 [PR #989](https://github.com/ybz21/Roami/pull/989)。

归档验收覆盖桌面四档宽度与 Redmi Note 8。逐卷打开九个历史专题，核对正文锚点、动态原型和旧账本快照返回。检查 36 个 HTML 和 528 条本地引用，在隔离目录重建三个迁移后的原型。15 条旧临时链接匹配到已有归档副本，其余临时证据在对应记录中标明。

| 页面 | HTML 设计 |
| --- | --- |
| 模型源 | [来源配置、模型启停和删除、WorkBuddy 账号](model-sources.html) |
| 聚合 | [免费候选筛选、拖动及生效调度顺位](model-aggregation.html) |
| 概况 | [用量、时区和限额](model-usage.html) |
| 监控 | [请求趋势、失败构成与排查入口](model-monitoring.html) |
| 审计 | [调用、费用和技术详情](model-audit.html) |
| 本机网关 | [人机交互、对外接口与控制接口](model-gateway.html) |
| 语音输入 | [识别服务与测试](model-speech.html) |

本稿在桌面 1280、1920、2560、3440 CSS px 和 Redmi Note 8 真机点通。覆盖聚合四种状态、失败时段和类别筛选、审计跳转、无调用状态及签到回执。运行统计和领取记录使用演示数据。

各设计页保留对应的现有 Roami 入口。聚合和监控样例可带着调用或时段条件打开审计页。

2026-11-19 [LLM Gateway 三层设计](model-gateway.html)。以 OKR 免费模型的 503 和聚合降级为例，联通人机交互、对外调用和控制接口。参考本机 `llm-gateway` 在 `1f1ffc1` 的策略顺位和来源健康实现，补充 [聚合调度观测样例](model-aggregation.html#strategy-observation)。桌面 1280、1920、2560、3440 CSS px 和 Redmi Note 8 验证零尝试拒绝、候选耗尽、切换恢复、输出中断、审计跳转、来源健康和策略草稿。现状核对基于网关调用路径与只读监控，示例原因使用演示数据。

2026-11-19 免费筛选与删除验收。隔离网关中复现旧配置对唯一积分成员的费用拦截，升级后可调度数从 0 变为 1。桌面四档宽度和 Redmi Note 8 验证筛选只作用于候选，已选成员保留。来源详情列出引用的聚合，未被引用的来源可通过确认框删除。七个 HTML 通过 Roami 文件预览打开，跨页审计保留时段与失败原因。截图见 [PR #989](https://github.com/ybz21/Roami/pull/989)。

2026-11-19 Magpie 社区导入验收。桌面和 Redmi Note 8 能搜索 `packages/workbuddy`，显示线上与本机版本。隔离节点从发布索引下载并校验 WorkBuddy 0.2.37，识别出 WorkBuddy 和 WorkBuddy AI。GitHub 官方、jsDelivr 和 gh-hk 选项通过目录读取验证，其中香港节点失败后回退成功。用模拟响应验证包摘要不匹配时拒绝导入。截图见 [PR #989](https://github.com/ybz21/Roami/pull/989)。

2026-11-19 聚合调度调整。把现有聚合详情的「运行状态」并入「调度」，在策略卡片上方显示可展开的「当前调度顺序」。生效顺位来自同一份网关状态。沿用原来的排序手柄、落点和「保存并应用」。用同一份测试配置对照桌面与安卓真机，核对生效顺位、跳过原因、拖动草稿及保存后重开。截图见 [PR #989](https://github.com/ybz21/Roami/pull/989)。

2026-11-19：[合并调度状态、统一模型源类型与 Magpie 插件更新](./history/prototypes/routing-status-and-sources.html)。可交互 HTML 含原型和技术设计。

原型已在桌面 1280、1920、2560、3440 CSS px 和 Redmi Note 8 真机验证。覆盖调度顺位、跳过状态和规则应用，来源筛选和创建，直接填写插件目录链接或仓库相对路径，以及模型选择和更新回退。插件安装和回退使用演示数据。

拖动交互以现有 Roami 调度页的浏览器 DOM 和计算样式为依据。原型验证了拖动阈值、上下落点、取消、列表外释放、草稿和应用。桌面验证键盘及边缘自动滚动，安卓真机验证触屏拖动与列表滚动。

2026-11-16：本机网关第二轮设计：[设计说明](gateway-design.md) · [可交互 HTML](./history/prototypes/gateway-prototype.html)。[正式实现与验收](gateway-implementation.md)。

2026-11-16：[交互稿正式实现与验收](interaction-implementation.md)。

历史交互评审稿：[完整交互设计](interaction-design.md) · [打开当时原型](./history/prototypes/interaction-prototype.html)。覆盖大模型七个页面及主要详情流程，使用演示数据。

## Product Design

本阶段只重构模型源和聚合。参考 Linear 的紧凑导航与对齐、Vercel Geist 的中性表面和明确对比。React + Tailwind CSS + shadcn/Radix 控件承载新页面，沿用 Roami 已有 token、国际化、手机导航与手势约束。其他能力页继续使用既有组件。

按用户最终确认，能力顶部 Tabs 和模型功能左侧 Tabs 保持原有形式；手机继续使用原有能力选择和顶部模型 Tabs。聚合调度采用上下结构：紧凑策略配置与预览卡在上，完整优先成员列表在下，编辑和预览不再分居两栏。成员用卡片式可排序行展示；鼠标悬停/键盘聚焦显示置顶和移除，触屏始终可见。

状态从已保存的真实路由渠道读取；新成员未检测时明确未知。上下文来自源目录；延迟只显示具有明确来源和时间范围的实际监控值，不推断、不造在线状态。监控仍为 24 小时滚动，保持原有空间上限。

## 配置减负与模型范围

- 聚合常用路径：名称、源、模型。自动生成 ID，默认智能策略。ID、启停和删除收在更多设置。成员列表可筛选已确认的免费模型，已选成员继续按保存的调度配置执行。
- 来源详情直接提供「删除来源」，确认后移除该来源和其名下启用的模型。有引用时列出相关模型，解除引用后即可删除。单个模型在「管理模型」内移除。
- 已有源先显示连接摘要与已启用模型；新增连接只先显示地址和 Key。名称、协议、认证方式按需展开。上游目录显式读取后分页展示，每页 30 项。
- 源内价格先显示当前规则及模型价格，点击修改后出现表单；模型级规则独立保存，明确免费仍须确认。
- 源清单与价格表、聚合候选共同使用 `configured-source-models.ts`：只认已保存的非聚合主模型。聚合引用、备用候选和上游全目录均不能自动扩展清单。
- 历史聚合中未在源里启用的成员保留并标记，可显式取消选择；从源移除模型不会删除对应聚合。聚合成员页不再发起上游发现请求。
- 手机将策略选择与细则放在同一行，预览与故障测试共用标题行，首屏优先显示完整成员。
- 成员选择改为左侧源、右侧模型，上方直接展示聚合池；跨源选择与移除不再切换已选视图。单模型隐藏搜索与全选。详见 [聚合成员选择](member-selection.md)。

## User Stories

- 我能在一屏内看到策略、效果和优先成员，沿用熟悉的能力和模型导航。
- 我能从手柄拖动模型排序，或用键盘上下/Home/End 排序；置顶和移除都有清楚名称。
- 我能看到来源、可用性和已公布的能力；未知与不可用不混为一谈。
- 我能跨源核对已选成员，在字段旁定位错误，切换标签或返回后继续草稿。
- 手机列表可以正常滑动，只有抓住手柄时才排序；控件、弹层和保存均可触达。

## Technical Design

Tailwind 使用前缀和隔离的 utility 层，由入口统一加载一次，避免懒加载路由拆 CSS 后丢失基础样式；不引入全局 Preflight，不改其他页面的默认元素。shadcn 风格的本地组件基于 Radix primitives，颜色、字号、圆角和空间映射现有 token。没有新增第二套全局主题。

`ModelHub` 保留目录与源详情路由和草稿逻辑，能力顶部 Tabs、模型左侧 Tabs 沿用原组件和布局。`ModelSourceEditor`、`SourcePricingSettings` 与聚合编辑控件迁入新组件。`RoutingStrategyPreview` 只显示紧凑模拟；`AggregationMemberOrder` 独立承载全宽成员列表。现有 Pointer Events 拖动保留触屏滚动和取消语义，新增置顶，移除上下移按钮。

元数据按唯一源读取、限制并发，目录请求按 revision 缓存，离开时取消。真实路由与监控最多各一组可见时轮询；新增草稿不查询虚构运行状态。排序、权重、ID 别名、定价和请求协议语义保持。

## Direction contract

THESIS: 让模型路由成为可操作的工作台，以优先列表为主体；配置和预览共同解释接下来会如何调度。

OWN-WORLD: 使用现有中性深浅表面、细边界、标准 sans 和唯一蓝/绿语义色，压缩内容区的配置和控件层级，外层导航保持原样。保留用户指定的独立卡片。

STORY: 先确认源与成员，再选策略；在同一区域观察预览，随后排序并保存。真实渠道状态始终与草稿示意区分。

FIRST VIEWPORT: 原有能力顶部 Tabs 和模型左侧 Tabs；详情标题和保存动作；顶部紧凑策略/模拟卡；下方全宽成员行。宽屏有更多行内指标，手机纵排但不缩小文字。

FORM: seed: none (pinned) — 用户指定“上下结构”“路由策略和调度预览合并”“下方全宽展示优先顺序列表”。签名交互为抓手拖动、即时更新调度示意和保持成员权重。

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Acceptance

导航修订：按用户最终确认恢复能力顶部 Tabs、模型左侧 Tabs；保留内部策略预览与拖拽重构。修订后重新完成四档桌面宽度、侧栏展开/收起及安卓真机导航、详情滚动、返回和定价路径验收。`acceptance.json` 的 `navigationRevision` 记录导航修订，`simplificationRevision` 记录最终配置减负与模型范围修复，`initialDesktop` / `initialPhone` 保留初版验收历史。

已验证桌面 1280/1920/2560/3440、侧栏展开/收起、深浅主题与中英文。Redmi Note 8 真机完成选源、拖拽、滚动、返回继续草稿、保存回读、原生键盘、定价切换和菜单操作；文档与编辑区均无横向溢出。

255 个前端测试文件、1,837 项测试通过；typecheck、i18n、hover、生产构建和完整质量门禁通过。配置减负与模型范围修订完成独立复核，手机密度与跨源计数两项修正均获 `ship`，结论覆盖这两项修正。设计检测无机械问题；独立设计复核要求为两个折叠区恢复展开标识，已补 SVG 箭头、打开状态和触屏命中区，复核结论为 `ship`，覆盖该项修正。验收使用隔离实例和模拟上游，未调用生产模型。详细结果见 [acceptance.json](acceptance.json)，截图由 PR 的 pr-shots 分支保存。

参考：[Linear UI redesign](https://linear.app/now/how-we-redesigned-the-linear-ui)、[Vercel Geist](https://vercel.com/geist/introduction)、[Tailwind Vite](https://tailwindcss.com/docs/installation/using-vite)、[shadcn Vite](https://ui.shadcn.com/docs/installation/vite)。

成员选择修订：按用户确认改为左源右模型、上方聚合池；手机池成员横向滑动，源与模型独立滚动。255 个测试文件 / 1,843 项测试、完整质量门禁和 Redmi Note 8 实机流程通过；针对该成员选择范围的独立完整复核结论为 `ship`，无材料级修正项。详见 `acceptance.json` 的 `memberSelectionRevision`。
