# 概况 / 审计实现与六页设计验收

日期：2026-11-12。

## 已实现

「能力 / 大模型」的原 `usage` 路由显示概况，保留今日全局用量和每日限额，剩余额度在费用未知时显示待核对，已知时按纳单位精确扣减；同时提供周期汇总、趋势、按模型源 / 智能体 / 模型分组、排序与下钻。新增同级 `audit` 路由，提供逐条调用、状态与关键词筛选、服务端分页、回执、耗时和请求时价格快照。旧链接继续兼容。

概况和审计不再嵌套内部 Tab。切换到其他模型管理页时保留筛选，后台停止页面读取；打开调用详情时暂停列表刷新。周期数据每 30 秒按可见性刷新，取消过时请求，隐藏时暂停，错误退避。搜索输入在分页请求期间保持挂载，避免请求完成后丢焦点。

今日用量读取全部调用，分析筛选不能改变每日额度口径。总 Token 为输入加输出，缓存读取属于输入；费用分币种合并，不换算相加；未知用量和费用保持未知。审计详情复用现有对账流程。

## 模块

- `ModelHub.tsx`：概况 / 审计导航、现有设置控制器和页面状态保留。
- `ModelUsageWorkspace.tsx`、`model-usage-workspace-state.ts`：数据读取、筛选、概况、分组、审计列表与详情；复用项目图表、金额合并、SVG 图标、返回按钮和手机二级页。
- `usage-workspace.go`：沿用已授权的 `/agent/model-gateway/usage` 入口，以 `view=overview / audit` 区分查询，保留原接口行为。
- `ledger.go`、`daily_retention.go`：schema v6 在日汇总中保留模型源 ID；归档迁移与计费整数约束一致。既有归档源不可恢复，明确进入未归属组。

新增审计查询支持起止日期、模型源、未归属源、智能体、模型、RSI / other 来源、状态、关键词和页码。关键词按普通文本匹配模型、记录 ID、请求 ID 和上游请求 ID；单页 20 条。返回的单价来自原始请求快照，不使用当前价格重算历史费用。

## 自动检查

- `npm run typecheck`、`npm run i18n:check`、`npm run hover:check` 通过；中英文语言包同步新增。
- 完整 `npx vitest run`：234 个文件、1708 项测试通过；后续搜索挂载与样式调整后，相关 33 项测试再次通过，包含新增的跨币种额度、纳单位精度及历史日期下钻检查。
- `npm run build` 通过，生产构建并压缩；存在仓库已有的 chunk 大小和 GitPanel 混合导入提示。
- `go test ./...` 通过。新增回归覆盖模型源归档前后不丢归属、旧库迁移、完整计数与分页、普通文本搜索、冻结单价、未知回执和非法筛选。
- `scripts/dev/quality/check.sh quick` 与 `git diff --check` 通过。新增前端模块没有 emoji 或文字符号图标。

未修改 Python 代码、依赖或运行资源，未执行 Python 依赖同步 / lint / 测试。

## 桌面 / 真机

隔离实例通过 `scripts/dev/isolated-roami.sh /tmp/roami-usage-product/home` 启动，使用独立配置、数据库与 tmux socket。65 笔确定性调用记录仅写入此测试库，未发起真实模型请求；修改测试每日限额也只作用于此实例。复用已安装的 Python 运行时提供接口转发，未修改其配置或模型路线。

桌面使用生产构建与真实接口，检查 1280 / 1920 / 2560 / 3440 CSS px，以及详情开启 / 关闭。验证限额保存、按源下钻、分页、关键词搜索、请求单价、未知值，以及筛选后的汇总 33 笔、今日额度仍覆盖全部 65 笔。页面无文档级溢出，详情关闭后释放宽度。

Redmi Note 8（`216d6a43`）通过 LAN HTTPS 使用生产页面。实际为 compact / coarse，页面宽度与滚动宽度均为 392 CSS px，筛选控件均达到 44 CSS px。真实触摸进入审计、展开筛选、滚动、打开全屏详情并返回；详情只有一个返回栏。返回后列表位置保持约 428.73 CSS px。

证据：[桌面](evidence/implementation-desktop.json)、[手机](evidence/implementation-phone.json)。

截图未提交主分支：`/tmp/roami-product-overview.png`、`/tmp/roami-product-audit-detail.png`、`/tmp/roami-product-phone-overview.png`、`/tmp/roami-product-phone-audit.png`、`/tmp/roami-product-phone-detail.png`。

## 六页原型

用户追加的六页设计已补齐静态 HTML。模型与连接支持搜索、连接编辑、模型选择和策略；价格页支持默认 / 覆盖单价；网关页支持命名密钥及启停；语音页支持服务商、语言、保存状态和明确标注的识别演示。所有交互均为原型内状态，不调用真实服务。

六页分别检查桌面四档宽度和安卓真机；连接 / 价格草稿跨页保留，手机连接编辑为可触摸的全屏页面。中英文导航及主要交互通过验证。

证据：[六页桌面](evidence/prototype-all-pages.json)、[六页手机](evidence/prototype-phone-pages.json)。这些页面的补充布局属于设计产物，现有产品连接、价格、密钥和语音配置流程没有被原型逻辑替换。

隔离验收服务及其专用 tmux server 已在验收后清理。静态原型预览服务保留，独立 HTML 可直接打开。
