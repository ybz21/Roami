# 实现与验收

2026-11-08。已在 `feat/async-session-lifecycle` 实现；未部署本机正式服务，未修改原生任务调度器。

## Product Design

创建、关闭先持久受理，再由后台完成。前端提交后即可离开；准备阶段显示同一稳定会话身份，不开放终端输入。原始需求和启动偏好随操作保存，开工由服务端执行。补充草稿按节点与会话保存，准备完成后由用户明确发送。

关闭先封住输入与新增占用，确认相关进程停止，再处理工作区。停止与目录清理分别保存回执；关闭、保留、已清理和需要处理分别展示。清理失败从原记录重试，用户可明确保留资源。关闭记录保存当时的短名称，避免会话退出列表后只剩内部 ID。

原生任务已有 task.run/task.close_session 继续作为状态权威，收尾入口投影其实际结果。本次没有新建 Python 队列，也没有给原生任务追加一套物理清理执行器。

## User Stories

- 创建被受理后离开或刷新，后台仍继续，重复请求不会多建资源。
- 准备阶段写补充，切换和刷新后仍在；尚未就绪时不发送。
- 勾选删除后关闭，确认框受理即退出，后台核对停止、目录和 Git 登记。
- 合并已经成功而删除失败，只重试未完成阶段；结果未知时暂停。
- 工作区出现新增内容、身份更换或新占用时，保留资源并显示需要处理。

## Technical Design

### 模块与状态所有者

| 模块 | 职责 |
| --- | --- |
| `internal/storage/schema.go`，schema 11 | 持久操作、同事务事件与动作幂等键 |
| `internal/sessionlifecycle/operation-store.go` | 不可变原始意图、版本 CAS、去重、资源与目录围栏 |
| `internal/sessionlifecycle/worker.go` | 跨进程 flock、阶段回执、重启恢复；创建与关闭各 4 个 worker |
| `backend/api/session-lifecycle*.go` | 受理、SSE、创建开工、关闭清理与旧接口 wait 适配 |
| `internal/tmuxruntime/lifecycle-fence.go` | 输入与目录租约、会话实例身份、创建/发送/恢复围栏 |
| `internal/memguard/pane-stop-proof.go` | 专用 systemd scope 停止与内核进程清空证明 |
| `backend/worktree/lifecycle-snapshot.go` | 实际分支、目录身份、完整文件内容及 ignored/untracked 核对 |
| `frontend/.../session-lifecycle.ts` | 共享读模型、持久请求键、受理占位和可见性事件订阅 |
| `SessionLifecyclePanel.tsx`、`lifecycle-draft.ts` | 收尾记录、动作、桌面侧栏、手机全屏页及草稿一致性 |

服务启动和停止共同管理 worker 生命周期；HTTP 客户端断开不取消已受理操作。资源阶段先写意图，再执行，最后写回执。Git 写操作沿用 common-dir 锁。服务退出后，未完成步骤先观察实际资源；无法核对的启动、合并或提交结果暂停，不盲目重放。步骤有 2 分钟期限，错误进入需要处理，由用户重试。

创建预先保存确定的 worktree 路径与所属操作，恢复时核对所有权，不自动换后缀另建。后台依次准备目录、创建会话、登记可选审查跟踪、投递启动；取消只补偿自身创建且仍安全的资源。关闭依次执行 inspect、stop、seal、commit、merge、remove、branch、trace；已完成的合并和分支处理独立保存。内容快照也覆盖忽略文件；提交钩子新增的文件不能成为下一次删除的默认授权。

### 实际接口

均在现有认证与节点路由内，路径加 `/api`：

- `POST /session-lifecycle/operations`：`{kind, requestKey, resourceId?, intent}`，事务提交后返回 202。
- `GET /session-lifecycle/operations`：活跃记录与最近 100 条结束记录；`?requestKey=...` 查询失去确认的受理。
- `GET /session-lifecycle/operations/:operation`：单操作。
- `POST /session-lifecycle/operations/:operation/:action`：retry / cancel / retain / retain-branch，携带 revision 与 requestKey。
- `GET /session-lifecycle/events`：使用持久 cursor 的专用 SSE，不借普通通知流制造通知。
- 旧 worktree 创建、派生与关闭接口等待同一工作流，不保留另一份副作用实现。

状态推送与兜底轮询复用共享请求。隐藏页面停止自己的连接与请求；结束态和需人工处理状态停止兜底轮询，重新进入或事件恢复刷新。

## 自动验收

- 最终完整门禁通过：Go 全量、格式、CLI 契约、前端 typecheck/i18n/hover/build、秘密与暂存策略检查。本次不涉及 Python 代码、资源或依赖，范围检查跳过 Python 运行时套件。
- 前端全量：217 个文件、1590 项通过。构建通过，保留已有大 chunk 提醒。
- Go 专项：API、worktree、sessionlifecycle 全部通过；隔离真实 Git/tmux/systemd 测试实际执行，未把 scope 缺失跳过算作通过。
- 覆盖并发同键受理、失去确认、版本冲突、阶段重启、原始启动文本、取消竞态、输入/占用围栏、停止回执、晚到文件、合并后删除失败与重试、启动结果未知、提交钩子新增 ignored 文件。
- 新增 UI 回归覆盖手机入口、硬件返回栈、桌面折叠侧栏展开、跨视图草稿一致性、唯一输入标签与关闭后的主题保存。

首次正常提交钩子发现新增 Git 测试漏清继承绑定，导致回归失败并影响当前分支名及 core.bare。已恢复原分支和配置，两处测试命令统一使用仓库现有的 Git 环境清理。另在一次性 guard 仓库绑定 GIT_DIR/GIT_COMMON_DIR/GIT_WORK_TREE/GIT_INDEX_FILE，实际重跑快照及隔离端到端测试通过；guard 的全部文件字节、分支、索引和配置保持一致。失败不记为通过，随后重跑完整门禁与正常提交钩子。

## 实机验收

独立目录 `/tmp/roami-async-lifecycle-ui-acceptance`；只使用其私有 tmux、Git 仓库、数据库和测试网页。未关闭用户现有会话，未向真实 Agent 发送任务。Android 为 Redmi Note 8，实际 ADB 点按、长按、输入和硬件返回；Roami Chrome 无法识别该手机浏览器时，CDP 仅辅助读取状态，触控仍由 ADB 执行。

| 检查 | 实际结果 |
| --- | --- |
| Git 锁占用时创建 | 202 返回 10.6 ms；后台等待仓库锁，前端可以离开 |
| 同一创建失败重试 | 沿用同一 operation/resource，解除锁后只有一个会话及目录 |
| 手机草稿 | 实际输入 Phone draft before ready；刷新后恢复；未自动发送 |
| 键盘 | 314 CSS px，输入区底边 437.89、键盘顶边 451；文档溢出 0 |
| 手机返回 | 详情返回列表，再返回主页面，不重复返回栏 |
| 手机关闭但保留 | 202 返回 19.6 ms，停止确认，目录和分支保留 |
| 手机默认勾选删除 | 202 返回 12.9 ms；后台结束后目录、Git worktree 登记及创建分支均移除 |
| 桌面布局 | 1280/1920/2560/3440 × 导航开关 × 侧栏开关，16 组通过；文档不滚动 |
| 桌面回收空间 | 收起侧栏后画布恢复 320 CSS px；显式收尾入口能重新展开折叠侧栏 |

这些是本机隔离样本的受理时间，不是 P95，不包含整个点击到确认框的时间，也不证明 Git、CPU 或内存变快。

### 边界

- 旧会话若没有可验证的专用 scope 停止证明，自动物理清理进入需要处理；不能靠会话不在就宣称写入已停止。
- 关闭确认前仍需读取现有 worktree 状态与完整内容快照，大仓库可能等待；受理接口异步化没有消除这段预检成本。
- 结果未知暂停，不承诺副作用 exactly-once；原生任务排队与执行容量沿用已有调度。
- 历史遗留 worktree 不由新后台流程自动批量删除。另按本次用户明确指令进行安全清理，记录见本机清理报告。
