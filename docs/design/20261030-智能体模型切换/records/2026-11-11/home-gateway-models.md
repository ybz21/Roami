# 首页选择网关模型

## Product Design

能力页已经保存 WorkBuddy 的 `WorkBuddy Hy4`、`hy4free`，但首页只读取当前直连服务的 `/models`。本机 Main 和 Worker 仍直连 Blade，返回的 11 个模型不包含这两个模型，因此首页搜索不到。

首页保留当前服务的模型，同时补充网关目录中尚未出现在该服务列表里的模型。选择网关模型时接入网关；连接失败时保留当前选择，错误提供重试或模型设置入口。复用现有桌面弹层和手机全屏模型页，不增加布局或控件。

## User Stories

- 用户在能力页添加 WorkBuddy 后，回首页搜索 `hy` 即可选择，不必先手动迁移连接。
- 只切换 Main 或 Worker 时，另一个角色继续使用原模型，并保留图片、上下文和推理参数。
- 目录修订过期、运行时忙或另一角色无法映射时，不覆盖原模型；刷新目录后可以重试，无法映射时提示先在模型设置绑定两个角色。

## Technical Design

- `useAgentModels.ts` 复用缓存的网关目录，把补充选择编码为临时 `gateway:` 标识，避免与直连模型同名 ID 混淆。保存时转回目录 ID，调用现有 `/model-gateway/catalog/roles`；成功后读回模型配置并广播现有更新事件。
- `roami_binding.go` 为 roles 接口增加互斥的 `{ role, model, revision }` 输入，沿用目录修订、禁用凭据、并发锁、原连接备份和运行时保存检查。
- 接入共享连接时，另一角色仅匹配同地址、同凭据、同上游模型的固定路由，或已经使用的网关 ID；恢复该角色的显式参数。找不到匹配时返回 `MODEL_ROLE_REQUIRES_BINDING`，不猜测替代模型。
- 网关凭据只在 Go 侧读取和应用，不返回浏览器。新提示通过现有中英文 i18n 提供。

## Acceptance — 2026-11-11

- 本机只读检查：运行时 `/v1/models` 返回 11 个 Blade 模型；网关目录包含另外两个 WorkBuddy 模型，原连接指向 Blade。
- `scripts/dev/quality/check.sh full`、`quick` 均通过；Python runtime 检查按改动范围跳过。
- 前端全量 Vitest：230 个文件、1,677 项通过。新增回归覆盖手机/桌面组件的目录补充、去重、网关绑定、Worker 切换和目录修订变化后的重试。
- `go test -race ./internal/modelgateway -run TestRoamiSingleRole -count=1` 通过，覆盖 Main/Worker、直连/网关、保留参数、过期修订和不可映射连接。
- 隔离实例目录 `/tmp/roami-home-hy/instance`，通过 `isolated-roami.sh` 启动；测试来源仅为本地目录服务，没有向真实模型发起生成请求，也没有修改用户的运行配置。
- Redmi Note 8 真机：ADB 打开模型页、输入 `hy`、点选 WorkBuddy；真实 Go 网关与 Python runtime 保存成功，Main 为 `workbuddy-hy4`，Worker 为原模型的 `existing-main` 网关路由。硬刷新后仍显示 `WorkBuddy Hy4`。模型选项高度 44 CSS px，命中检查和横向溢出检查通过。
- 1280、1920、2560、3440 CSS px 的宽屏布局通过 Android Chromium CDP 验证：工作台开/关共八种状态下，模型列表和选项可命中、无横向溢出，关闭工作台释放 440/640 CSS px 给对话。此项仍是粗指针模拟宽屏；本机桌面 Chrome 多个独立测试进程出现 `Failed global descriptor lookup: 7` 或 CDP 超时，未宣称完成真实桌面鼠标验收。
- 本地验收产物位于 `/tmp/roami-home-hy/`：`phone-models.png`、`phone-search.png`、`phone-selected-web.png`、`wide-results.json`、`wide-panes-results.json`。一次性截图不提交进主分支；后续 PR 截图应使用 `pr-shot.sh` 发布。
