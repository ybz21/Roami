# 创建会话选模简化验收

本修订撤回独立选模服务、会话选模表与 schema 29、选模预校验接口、三个专用请求头、目录版本握手、已有会话切模 Hook 和 `roami agent new` 的新增选模参数。

保留 `roami model list`、新建 Roami 会话指定模型和免费限制。模型复用任务原有 `intent_json.model`；仅免费随任务记录保存，执行走原有 Provider 和 Go 网关目录路由。

## 验证范围

- 任务选模幂等与保存；并行请求选模互不污染默认值、共用既有连接；原生任务实际执行收到选定模型。
- Go 网关按请求模型路由，移除本机免费字段，免费条件不满足时拒绝；角色默认设置和准入规则仍有效。
- 删除选模表后不再升级数据库，历史迁移回归保持原样。
- Go 全量检查通过；删除遗留 Web 路由后的 `backend/server`、`internal/modelgateway`、`cmd/roami` 补充检查通过。
- 前端 typecheck、i18n、hover、258 个文件 / 1883 项 Vitest 与生产构建通过。
- 真实隔离链路的 CLI、桌面、Android 三个原生任务成功；创建重试返回同一回执。默认 Worker 仍为 `default-worker`。
- 免费路线耗尽以 `MODEL_ROUTE_NO_AVAILABLE_MEMBER` 失败；不存在的模型以 `MODEL_NOT_CONFIGURED` 失败。付费夹具调用和本机约束字段泄漏均为 0。
- 新隔离实例数据库维持 schema 28，无 `conversation_models` 表。
- 桌面 1280 / 1920 / 2560 / 3440 CSS px 无文档或会话内容横向溢出；Android 实机 392 × 766 CSS px、314 CSS px 键盘下真实触摸创建成功，无页面异常。
- 两份设计 HTML 已同步、实际打开，无脚本异常。
- 简化版本的 `quick` 与 `full` 均通过：Python 4902 通过、48 跳过、6 项 subtests 通过。新增委派工具参数后重新执行最终门禁，结果完成后补充。
- 委派工具、任务选模、路由策略的针对性回归 59 项通过；工具公开 schema 包含 model/freeOnly，并保存进原有任务记录。
- 首页选择器的原生/聚合、未知类型、别名和动态目录变化已增加验证，前端 1883 项通过。

此前 `runtime-acceptance.md/json` 属于简化前的历史验收；其中会话切模、预校验与独立选模表的结果不再代表当前版本。


证据保存在本次节点 `/tmp/roami-model-simplification/`：`runtime-verification.json`、`desktop-layout-verification.json`、`phone-create-verification.json`、`document-verification.json`。截图通过 `pr-shots/pr-939/simplified-*.png` 随 PR 展示，不提交至 main。

仅本机协议夹具参与推理验证，未部署任务分支；以下 WorkBuddy 故障修复单独使用宿主已保存的网关配置验证。

## WorkBuddy 现场修复

用户提供的失败截图对应 `MODEL_NOT_CONFIGURED`；两个已登录的插件账号当前均提供 `hy4flash-free`，而保存的单模型和聚合池仍有 5 处 `hy4free` 引用。

通过现有目录 API、当前 revision 修正这 5 处引用，并合并替换后相同的聚合成员。模型入口 ID、账号、凭据、Main/Worker 选择保持原绑定；原始目录备份仅在本机以 0600 权限保留。没有在 Agent 代码中写入 WorkBuddy 特例。

直接请求原网关入口 `workbuddy-hy4`，实际使用 `hy4flash-free`，HTTP 200、无流式错误、返回 `OK`。该验证保留用户当前选中的 Main 模型。脱敏结果位于 `/tmp/roami-model-simplification/workbuddy-direct-verification.json`；备份与凭据不进入仓库。
