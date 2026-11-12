# 派生任务提示词与 Main 回复展示

第二轮：见 [统一开工、回报与产物约定](unification.md)。

第三轮：见 [能力说明改为命令索引](capability-index.md)。

最终核对：见 [原版覆盖与精简核对](coverage-audit.md)。

## 产品设计

派生项目和专业执行器沿用新建任务的 Markdown 结构：任务原文置顶，随后是开工准备、交付要求、执行资料和本机能力。长命令使用 fenced code block；CLI 和任务上下文路径各声明一次，以带引号的变量引用。执行标识放到末尾，不占据任务开头。

Main 的回复生成和核对通过已有回复预览表达。`reply`、`task_reply`、`task_queue_reply`、`ask_user` 是回复交付流程，不再作为主聊天中的独立工具卡重复展示；原始调用状态与详情继续留存，真实回合失败和任务进展仍然显示。

## 用户故事

- 打开派生项目会话，第一屏直接看到本次任务，之后按需查阅执行指引。
- 续接任务时只看到新增要求，不重新带入旧目标；能力上下文绑定最新执行和任务版本。
- Main 核对回复时看到一份有状态的预览，完成后显示正式回复，不再紧跟一张“调用 reply”的内部记录。
- 回复失败时仍能看到真实失败状态，不因隐藏交付工具卡而误认为成功。

## 技术设计

- Python `CodingExecutor.run` 组装 Markdown 提示词，并声明 `promptFormat=markdown-session`；专业能力说明由前置改为追加。当前会话的稳定 ID 从 Go 启动回执注入。
- `ProfessionalCapabilities.brief` 保留签名上下文、权限和幂等规则，仅调整文案与 Markdown 结构。
- Go `Spec.PromptFormat` 明确区分新格式。`sessionPrompt` 对旧 spec 保持字节一致，避免改变已有执行的提示词哈希；新格式将唯一执行标识附在末尾，仍区分正文相同的不同执行。
- `agentTimeline` 只过滤交付工具的聊天投影，快照、SSE 活动数据和执行记录不变；同名的 `kind=turn` 失败提示不被过滤。
- 提示词属于 Agent 对话正文，按国际化规范的例外使用中文；普通开工简报的会话说明提供中英文翻译。

## 验收

验收结果与命令见本目录后续记录。截图等一次性产物保存在 `/tmp`，不提交到主分支。

### 已完成的专项验收

- 受管能力、续接、原会话提交及蜂群任务：257 项通过；真实 Python/Go CLI 续接与恢复专项通过。中文提示词同时覆盖了交互式夹具的 UTF-8 输入。
- 补充的执行资料 Markdown、路由及蜂群授权上下文：53 项通过。
- 前端全量：233 个测试文件、1705 项通过。回复投影覆盖 running、succeeded、failed、unknown；同名回合失败和任务卡保留。
- 真实 `AgentConversation` 组件使用隔离快照与 SSE 验收，未操作线上对话或调用付费模型。桌面 1280、1920、2560、3440 × 侧栏开关均无横向溢出；核对中只有一份预览，完成后预览为零并显示正式回复，失败仍有回合错误提示。
- Android Redmi Note 8 经 LAN HTTPS 加载同一组件，`data-pointer=coarse`，无横向溢出。ADB 真实点按打开思考强度菜单；长消息真实滑动使内部 scrollTop 从 866.91 变为 613.82，文档不滚动，reply 工具卡始终为零。
- 本次验收聚焦消息组件；未修改应用导航栏或页面壳层。手机 CDP 的 `roami chrome` 返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`，故通过该设备的 ADB 转发连接原生 CDP 完成断言和截图。

本机验收产物：`/tmp/roami-derived-task-prompt.md`、`/tmp/roami-main-reply-after-desktop.png`、`/tmp/roami-main-reply-after-phone.png`、`/tmp/roami-main-reply-settled-phone.png`、`/tmp/roami-main-reply-layout.json`、`/tmp/roami-reply-phone-touch.json`。这些文件不纳入仓库；公开 PR 截图按 `pr-shots` 规则另行上传。

### 门禁范围

Go 全量 `go test ./...` 通过。未收敛的 Python 完整套件在未改动的 RSI 场景耗时较长，已明确中断，不将其记为全量通过；期间发现的 CLI 测试仍按旧顺序要求任务正文在末尾，已改为检查 Markdown 任务置顶，并单独复测通过（1 项）。后续 quality full 的 Python 选择范围显式设为该跨语言用例；受管提示词、续接、路由和授权的两组专项结果（257 项和 53 项，部分覆盖重复）另记在上方。未运行真实模型验收或更改节点模型配置。

最终范围门禁通过：`PYTEST_ADDOPTS=tests/test_cli_integration.py::test_go_coding_execution_tmux_replay_cancel_and_unknown scripts/dev/quality/check.sh full`（经隔离启动器运行）。Go 全量、Python lint/format 与指定跨语言用例、前端 i18n/hover/typecheck/build、secret scan 均通过；前端 Vitest 全量另行通过。`git diff --check` 通过。本任务的开发服务器、测试 tmux 实例、测试标签和 ADB 转发均已清理；未提交、开 PR 或部署。
