# 模型源与聚合：工作台重构

2026-11-19 [大模型七页改进设计](model-monitoring-and-aggregation.html)。总览串联七页，每页提供独立章节和现有 Roami 页面入口。聚合成员承载、故障切换、监控失败构成和 WorkBuddy 签到均有可点的局部样例，包含数据口径、实施顺序与验收场景。

本稿在桌面 1280、1920、2560、3440 CSS px 和 Redmi Note 8 真机点通。覆盖聚合四种状态、失败时段和类别筛选、审计跳转、无调用状态及签到回执。运行统计和领取记录使用演示数据。

总览和七个独立章节通过 Roami 文件预览验证。桌面逐一打开七个现有页签，安卓验证章节跳转、本机网关入口和带条件的审计样例。

2026-11-19 聚合调度调整。把现有聚合详情的「运行状态」并入「调度」，在策略卡片上方显示可展开的「当前调度顺序」。生效顺位来自同一份网关状态。沿用原来的排序手柄、落点和「保存并应用」。用同一份测试配置对照桌面与安卓真机，核对生效顺位、跳过原因、拖动草稿及保存后重开。截图见 [PR #989](https://github.com/ybz21/Roami/pull/989)。

2026-11-19：[合并调度状态、统一模型源类型与 Magpie 插件更新](routing-status-and-sources.html)。可交互 HTML 含原型和技术设计。

原型已在桌面 1280、1920、2560、3440 CSS px 和 Redmi Note 8 真机验证。覆盖调度顺位、跳过状态和规则应用，来源筛选和创建，直接填写插件目录链接或仓库相对路径，以及模型选择和更新回退。插件安装和回退使用演示数据。

拖动交互以现有 Roami 调度页的浏览器 DOM 和计算样式为依据。原型验证了拖动阈值、上下落点、取消、列表外释放、草稿和应用。桌面验证键盘及边缘自动滚动，安卓真机验证触屏拖动与列表滚动。

2026-11-16：本机网关第二轮设计：[设计说明](gateway-design.md) · [可交互 HTML](gateway-prototype.html)。[正式实现与验收](gateway-implementation.md)。

2026-11-16：[交互稿正式实现与验收](interaction-implementation.md)。

最新交互评审稿：[完整交互设计](interaction-design.md) · [打开可交互 HTML](interaction-prototype.html)。覆盖大模型七个页面及主要详情流程，使用演示数据，尚未接入生产页面。

## Product Design

本阶段只重构模型源和聚合。参考 Linear 的紧凑导航与对齐、Vercel Geist 的中性表面和明确对比。React + Tailwind CSS + shadcn/Radix 控件承载新页面，沿用 Roami 已有 token、国际化、手机导航与手势约束。其他能力页继续使用既有组件。

按用户最终确认，能力顶部 Tabs 和模型功能左侧 Tabs 保持原有形式；手机继续使用原有能力选择和顶部模型 Tabs。聚合调度采用上下结构：紧凑策略配置与预览卡在上，完整优先成员列表在下，编辑和预览不再分居两栏。成员用卡片式可排序行展示；鼠标悬停/键盘聚焦显示置顶和移除，触屏始终可见。

状态从已保存的真实路由渠道读取；新成员未检测时明确未知。上下文来自源目录；延迟只显示具有明确来源和时间范围的实际监控值，不推断、不造在线状态。监控仍为 24 小时滚动，保持原有空间上限。

## 配置减负与模型范围

- 聚合常用路径：名称、源、模型；自动生成 ID、默认智能策略。ID、启停和删除收在更多设置；免费调用限制保持可见。
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
