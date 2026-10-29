# 恢复本地计费页面 · 2026-10-29

[主题设计](../../README.md)

## Product Design

在「设置 → 模型与连接」恢复「模型连接 / 代理与计费 / 模型单价」三个标签。沿用原统计、图表和价格编辑组件，数据和保存操作接入本地 Go 网关。移除原先跳转云端管理页的主流程，保留模型服务地址与密钥设置。

计费页显示今日费用、用量、统计周期和最近请求，并可调整每日限额、币种和账期时区。单价页提供默认单价与按模型的输入、输出、缓存价。全部价格使用同一账本币种。最近请求中的未知费用提供短核账对话框，输入已核对金额和依据后才提交。

## User Stories

- 切换连接、计费和单价标签，不丢未保存输入；离开再回来，复用既有设置草稿恢复。
- 在计费页查看近 7/30/90 天、累计，或选择日期查看分时与模型明细。
- 保存失败时保留全部草稿，显示恢复方向；核账刷新统计时也不覆盖配置草稿。
- 手机上通过一个返回栏进入设置子页，保留主导航，触摸操作不依赖悬停；键盘弹出时聚焦字段避开固定保存条。

## Technical Design

`AgentSettingsWorkspace` 管理 URL 标签、模型配置表单及共享的网关设置状态。`useGatewaySettings` 拥有配置快照、草稿、保存、目录和核账；两个计费标签共享该状态。旧模型连接写入 `/agent/model-settings`；本地价格、限额、核账和统计只访问 `/agent/model-gateway/*`。不读取归档的 `/agent/model-usage`。

`local-model-gateway.ts` 将 Go 分组账本适配到原统计组件，金额合并采用 BigInt 纳单位；图表只将数值用于绘图，不用浮点数拼合显示金额。按模型、日期和时段汇总保留不同币种与未知费用，人工核账不补造缺失 token。累计趋势最多展示最近 90 天，周期总额保留完整累计数据。

Go `StatisticsFor` 增加指定日期、时区分时和累计统计；今日摘要独立于所选日期。页面无新增轮询，按标签激活、日期范围、保存和核账更新请求，取消过期读取。

## Acceptance

- Go 全量与 Python 回归已通过；本轮全量日志中 Python 为 1843 项通过、14 项跳过。
- 前端全量为 144 个文件、1042 项通过，包括草稿跨标签保留、失败后重试、未知费用显式核账、日期查询、纳单位汇总与键盘打开后的字段避让。
- typecheck、i18n（4395 个键）、hover 与串行生产构建通过；补跑仓库原策略检查，包含新源码的密钥扫描与 staged 文件规则通过。统一 full 脚本的 Go、Python 和前端基础检查已通过，其构建压缩阶段因两份构建同时写同一 dist 目录而失败；停止重复构建后，单独串行重跑整个前端生产构建并补齐其后策略检查通过。日志分别为 `quality-full.log`、`build.log`、`policy.log`，不将首次脚本失败写成门禁一次通过。
- 真机 Redmi Note 8，LAN HTTPS，392 CSS px / coarse pointer。真实触摸完成单价 2 → 3.5、限额 20 → 25，并通过 Go API 确认保存且互不覆盖；更改已固定账期的时区返回真实 409，草稿保留，显式还原恢复原值。
- 真实触摸将一笔未知费用核对为 0.75 CNY；统计重新读取、未知费用动作消失，Go 记录保留核账依据。刷新后限额仍为 25。
- 软键盘实测高度 314 CSS px，底部导航隐藏；修复后输入框底边约 334.91，保存条顶边约 363.82，输入不再被保存条遮住。通过返回栏回到设置，再从底栏进入首页、设置和模型页，保存值仍为 25；指定日期分时接口返回真实时区小时数据。手机滚动位置从 236.73 变为 0，文档宽高均无溢出；顶栏约 60.73 CSS px，底栏含安全区约 84.73 CSS px；触屏 tooltip 隐藏。

本次全部在 `/tmp/roami-local-gateway-ui-20261029/` 的隔离 HTTPS 实例验证，数据为专用夹具，不包含用户对话或付费模型请求。原有画面由当前 HEAD 的前端源码构建，用于改前截图。原生 Chrome CLI 无法识别 Android 浏览器身份，手机使用仓库验收清单允许的 ADB + CDP 执行；触摸使用 `Input.dispatchTouchEvent` 和手势合成，未以 `element.click()` 代替命中测试。

证据目录：桌面 `desktop-before.png`、`desktop-billing.png`、`desktop-prices.png`；手机 `phone-billing-after.png`、`phone-prices.png`、`phone-reconcile.png`、`phone-keyboard.png`；动作断言 `desktop-checks.json`、`phone-checks.json`、`keyboard-navigation-checks.json`。

验收汇总：`/tmp/roami-local-gateway-ui-20261029/acceptance.json`。隔离实例与任务创建的浏览器页在验收后关闭，用户现用服务未部署或重启。
