# 统一 CLI 对齐 · 技术 v2

依据：[CLI 统一设计 v4](../../20261017-CLI统一设计/index.html)，源码基线 `a27f13a`（#328）。本轮只更新设计，不修改运行时代码。

| 边界 | Agent 设计中的落点 | 当前状态 |
|---|---|---|
| 一个 Go module / 一个入口 | 根 go.mod、cmd/roami；Python 保持独立包，不增加第二套 Go CLI | 统一入口已合入；Agent 未实施 |
| 正式命令树 | roami session / chrome / project / db / auth；ttmux、chrome、roami ttmux 仅兼容 | 已有 |
| Go 内部会话调用 | Web 复用 internal/application / internal/session；backend/ttmux 默认进程内调用 | 已有；显式外部 CLI 兼容路径仍保留 |
| Python 外部调用 | RoamiCLIExecutor 用 argv 调统一 CLI；JSON stdout 与 stderr 分离，设超时 | 候选适配，未实施 |
| 项目单写 | roami project 经 API client 与已有 Go auth 调 ProjectService；Python 只保存核心资源引用 | 项目 CLI 已有；Agent 调度未实施 |
| 新任务工作区 | 经 Go 共享 worktree 能力成功 fetch，固定本次远端 OID 后建分支 / 工作区，绑定目录后启动 Agent | 远端准备底层已合入；幂等结构化 prepare 用例与 CLI/API 适配待补 |
| 继续旧任务 | 不自动 reset/rebase；不建 worktree 的逻辑 Fork 不触发 fetch | 沿用统一设计 |
| Agent 回报 / 回复 | 在 cmd/roami 明确注册 agent report / reply，薄适配到 Python ReplyService；返回原始主对话 | 拟新增，不能当作当前可执行命令 |
| 数据目录 | DatabaseRoot/agents/runtime.db；DataRoot/agent-artifacts；RuntimeRoot/agent.sock | Agent 路径约定待实现；统一 Go 路径解析已有 |
| 目录与版本 | Go catalog 登记 agent-runtime / agent / python-agent，pending→ready；Python schema_meta 版本迁移 | 目录基础已有；Agent 登记桥接未实现；候选 DDL 已调整 |
| 维护锁 | Python 持有现有 storage.lock 共享 flock 与 Agent 独占锁；维护前停 Python，Go 独占 storage.lock | Go 锁已有；Python 协作待实施 |
| 备份恢复 | roami db 统一入口编排；在现有数据库备份集外增加产物 hash、文件、schema 兼容验收 | 数据库备份已有；Agent 完整恢复包未实施 |
| 浏览器 | roami chrome → backend/browser/automation → 原有 Node/Playwright/CDP/profile | 统一浏览器入口已有；Agent Browser Driver 待实现 |

## 数据所有权

Go 的 meta.db 保存既有项目、会话与蜂群元数据。Python Agent 库保存主对话、任务、记忆、事件、上下文与投递。两者通过稳定 ID 关联，不跨库写业务表，不把 Agent 记忆塞进项目 CLI 的元数据表。

Go 负责统一路径、catalog 与维护协调，不拥有 Agent 业务 DDL；Python 负责自己的 schema 版本与业务事务，但不能绕开平台维护锁。当前候选 schema.sql 用 schema_meta 暴露版本供备份清单读取，不能据此推断完整平台集成已经完成。

## 后续实施顺序

1. 薄 Go 初始化适配：统一解析并传入路径与 instanceId，登记 Agent DB，验证 schema 支持范围。
2. Python 维护锁 / 单实例锁、DDL 迁移与数据库 writer，验证跨进程维护互斥。
3. Main 保存对话、模型流式输出与 Go 透明转发，先验收快问快答。
4. 共享 TaskWorkspace 结构化准备与幂等资源回执，再接 Python CLI 执行器和 report / reply。
5. 扩展备份产物编排与恢复验收，补齐记忆、缓存和 Browser / Computer 能力。

新入口必须做干净 PATH 验收：仅有正式 roami 与系统运行时，也能完成 Agent 派活与浏览器观察；不依赖旧独立 ttmux/chrome 产物。接口名和 Agent catalog kind 均为候选，实施时注册到统一核心，不发布另一个 CLI 产品。
