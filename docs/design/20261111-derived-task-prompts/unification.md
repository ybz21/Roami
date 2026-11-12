# 统一开工、回报与产物约定

## 产品设计与用户故事

上一版只统一了外观，派生提示词仍在 Python 中独立拼接交付要求，产物说明还依赖附件或路由资料分支。用户无法确认执行器如何向 Main 回报、回报什么，以及产物如何保存。

现在所有入口共用 `backend/api/prompts/task-execution.md`：开工与执行、过程回报、产物交付、完成回报。入口仅补充它实际拥有的工作区信息与返回通道，不拼造不存在的回调能力。

- 新建任务和文件入口在任务、工作区准备之后读取统一约定，再追加普通工作会话的返回方式及可编辑本机能力。
- Main 派生的专业执行器与 Roami 原生子智能体无条件接收统一约定；完整任务绑定由宿主和私有上下文持有；没有附件或路由资料时也不会遗漏产物说明。
- 蜂群任务再附带绑定当前 taskId、runId、taskRevision 的群聊 JSON 与命令示例。
- 旧普通会话派发沿用其已实现的显式返回通道，提供合法 JSON、实际 dispatch 命令、重试和失败要求。

## 各入口的回报与保留方式

| 入口 | 如何回报 | 产物如何交付 |
| --- | --- | --- |
| 用户直接新建的会话 | 当前会话说明与最终回复；无绑定时不声称已通知 Main | Roami 文件链接依赖原文件，保留工作区 |
| Main 受管任务 | 执行器结束后宿主采集结果、收集产物、验证并生成原 Main 的完成回调；不要求执行器自行调用 report API | 最终答复列出工作区内真实文件的绝对路径链接，宿主校验并保存产物，返回 downloadUrl |
| 蜂群成员 | 过程讨论、问题、阻塞或移交使用实际群聊返回通道；最终结果仍走受管任务完成链路 | 与受管任务相同，群聊接收回执不能替代产物保存或验收 |
| 旧会话派发 | 写 UTF-8 JSON 后调用绑定 dispatchId 的 `roami agent reply`，检查接收回执 | 当前此旧通道不自动归档本地文件；保留源文件，使用可点击文件链接或已有 downloadUrl |

普通受管任务没有额外手工进度回调命令，宿主按执行器支持情况采集过程记录，不承诺每条过程说明都会即时发进 Main。完成回报、产物保存和任务验收分别表达；执行器不能通过一句“完成”或一次群聊回执覆盖宿主状态。

## 技术设计

- 唯一基础源：`backend/api/prompts/task-execution.md`。
- 通道源：相同目录的 `task-report-session/managed/legacy/swarm.md`，只保留各入口必要的协议差异。
- Go `AgentCapabilities` 通过原接口额外返回 `executionGuide`；`content` 及可编辑能力文件的内容和空值语义保留。统一执行约定独立于可编辑能力说明，后者留空不再关闭执行和交付要求。
- 前端 `loadAgentCapabilities` 合并固定执行约定和可编辑能力，工作区简报、语言标题和节点文件 URL 替换继续使用原实现。
- Python `context/execution_brief.py` 从相同 Markdown 源生成受管通道说明、合法蜂群消息和旧会话返回通道。专业执行器直接组装，Native 通过可信的 executionBrief 传给上下文构建器。没有数据库绑定的独立 NativeExecutor 不虚构 Main 或任务版本。
- `professional_brief` 只补充附件、路由和授权资料，不再维护另一套产物交付规则。
- `case_build.py` 将相同文件打入 wheel 与 sdist；安装后的资源读取不依赖源码仓库。RSI 镜像按白名单复制这些提示词，不扩大为引入整个 backend 或评测数据。

## 完成与产物数据链路

执行器在最终结果中提供实际结果与文件绝对路径。宿主把其与当前任务、执行、版本及工作区绑定，独立读取和保留明确报告的文件。产物记录包含 id、taskId、name、mimeType、sizeBytes、sha256、downloadUrl，并记录本次 runId、源文件位置等元信息。

原 Main 的完成回调携带 taskId、runId、taskRevision、权威任务 state、宿主执行回执及 result；result 中的 artifactRefs 指向实际保存的产物。Main 使用这些已登记链接向用户交付，不重新猜文件路径，也不把执行器的 succeeded 直接当作任务已验收。

HTML 交付优先采用自包含文件；多文件交付须明确列出资源并检查各项保存结果，不能只归档入口文件。未知、丢失、越界、不支持或保存失败的文件不承诺为已交付产物。

## 验收与样例

- 离线模型夹具实际走过：Native 写文件、宿主保存产物、完成回调到原 Main、Main 返回下载链接。删除工作区原文件后，保存的产物仍可读取。
- 该夹具的执行结果为 succeeded，任务状态为 waiting_user；回调保留两者差别，没有伪造已验收。
- 原始记录：`/tmp/roami-unified-delivery-evidence.json`；可读样例：`/tmp/roami-unified-callback-and-artifacts.md`。样例中的下载地址属于离线实例，不是线上可用链接。
- 普通新建任务样例：`/tmp/roami-unified-new-task-prompt.md`；派生任务样例：`/tmp/roami-unified-derived-prompt.md`。

样例与截图不纳入主分支；本轮检查结果在完成后补记。没有调用付费模型，没有改变节点保存的模型路由或参数，没有部署线上服务。

### 本轮最终检查

- API 与真实 Go 执行器相关包：`go test ./backend/api ./internal/agentexecution` 通过，覆盖持续会话、续接、恢复、生命周期与提示词绑定。
- Python 第一组 311 项中，310 项通过；缺少数据库绑定的独立 NativeExecutor 最小调用夹具暴露了不应假设存在 Main/版本的问题，已改为仅绑定数据库任务时注入受管回报通道，并在后续 68 项专项中通过复测。
- 后续 81 项中 79 项通过；两项仍检查旧英文产物句子的续接断言，已改为验证统一约定、真实路径、宿主保存、当前 runId/版本与旧身份失效，两项单独复测通过。Main 旧会话派发的 4 项回归通过；发布包与容器源码资源读取的 4 项回归通过。
- Python lint、format、前端 typecheck/i18n/hover/build 通过；Vitest 233 个文件、1706 项通过。没有把 Python 全仓 RSI 套件记为本轮通过。
- wheel 与 sdist 均包含 6 份规范模板，逐字节与唯一来源一致；安装包脱离源码仓库可读取。容器源码布局读取路径有回归覆盖，未声称已完成整个 Docker 镜像构建。
- 新建任务与派生任务的实际生成样例各包含且只包含一次同一基础约定，没有未替换的模板变量。
- 真实 Go API + 现有 kickoff 模块 + 真实消息 Markdown 组件验收：1280、1920、2560、3440 宽度无横向溢出；Android 经 LAN HTTPS 验证 coarse 指针，ADB 点按切换至派生任务，真实滑动使内部 scrollTop 从 1416.73 变为 1770.55。产物与回调说明均可阅读。
- 手机截图：`/tmp/roami-unified-new-task-phone.png`、`/tmp/roami-unified-derived-phone.png`、`/tmp/roami-unified-callback-phone.png`；布局与触控断言：`/tmp/roami-unified-preview-check.json`、`/tmp/roami-unified-touch.json`。这些为隔离预览，不是线上任务。
- 离线真实运行时回调样例另保留了经 SHA256 核验的可读文件副本：`/tmp/roami-unified-demo-report.md`。
