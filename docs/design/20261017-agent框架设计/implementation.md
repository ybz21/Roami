# 实现进度 · 2026-10-17

当前分支 `feat/agent-runtime`，基线 `a27f13a`；目标保持完整 Agent 框架，不以单元测试通过代替运行时交付。

已开始实现 Python 存储、对话、记忆、上下文压缩、provider、委派 / Fork 和主动通知基础服务，详见仓库 `agent-runtime/README.md`。18 项临时库 / 注入模型测试通过。

尚需 Agent Loop / Worker、工具、真实 CLI executor、Go 统一入口 / catalog 桥接、HTTP / SSE、斜线命令、前端与系统通知集成。工作台必须保留项目 / 会话树、历史对话、项目快捷建任务、原始对话回报和手机导航。主动通知需补触发策略、调度、免打扰、可见消息确认与 App 适配。

Memory 的后台提取 / 每日汇总、完整忘记传播与来源屏蔽、缓存和 ancestor 总预算仍需继续实现；当前已落地源追踪、版本、FTS、删除 tombstone、快照失效与深度 / 直接子任务并发约束。

没有部署生产服务，没有启动真实编码 Agent，也没有宣称框架已完成。

## 可运行内核与统一入口

已接通 Runtime 模型循环、独立 Main / Worker 容量、按轮次组装上下文、手动 / 自动压缩、工具调用、子任务汇合、共享祖先步骤预算、验证与主对话回报；新增 FastAPI HTTP / SSE、六个命令与私有回调。统一 roami agent setup/init/serve/status/new/send/history/report/notify 已可运行。Go 使用现有鉴权组和固定私有 Socket 透明代理，私有回调未对公网挂载。

实际验证包括 Go→目录登记→Python 私有 Socket→本地 HTTP 模型夹具→持久化回答→CLI 历史 / 主动消息，以及维护锁排斥。模型使用测试服务，并非已接真实账号。生产前端、外部编码执行器、MCP、调度 / 免打扰和 App 推送仍未完成。
