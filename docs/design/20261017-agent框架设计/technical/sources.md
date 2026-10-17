# 技术依据与设计选择

查阅日期：2026-10-17。以下是本轮实际打开的官方文档；供应商接口可能演进，实施时仍须按所选模型 / SDK 的实际能力锁定配置。

| 官方来源 | 对应设计 |
|---|---|
| [Pi Agent Core](https://github.com/badlogic/pi-mono/blob/main/packages/agent/README.md) | 轻量循环、事件与消息边界；初轮调研 |
| [Pi Compaction](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/compaction.md) | 追加式压缩条目、近期消息与工具块；初轮调研 |
| [OpenClaw Runtime](https://github.com/openclaw/openclaw/blob/main/docs/agent-runtime-architecture.md) | 区分内核与外围服务；当前版本不能假定始终直接依赖 Pi |
| [OpenAI Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) | 不同模型代际的缓存参数、前缀与 usage；只在 provider adapter 内映射 |
| [OpenAI Cache diagnostics](https://developers.openai.com/api/docs/guides/prompt-caching/diagnostics) | 缓存未命中排查与指标 |
| [Anthropic Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) | cache_control 与读写输入用量分开统计 |
| [SQLite WAL](https://www.sqlite.org/wal.html) | 日志与读写、备份 / checkpoint 约束 |
| [SQLite FTS5](https://www.sqlite.org/fts5.html) | 全文检索、trigram 对短查询的限制 |
| [Python sqlite3](https://docs.python.org/3/library/sqlite3.html) | 连接 / 事务与 backup API |
| [FastAPI StreamingResponse](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse) | Python 流式响应的实现入口 |
| [Go ReverseProxy](https://pkg.go.dev/net/http/httputil#ReverseProxy) | Go 透明代理、Rewrite 和 flush |
| [MCP Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) | MCP 传输边界，首版使用明确协议版本 |

| [Chrome DevTools Accessibility](https://chromedevtools.github.io/devtools-protocol/tot/Accessibility/) | Browser 可访问性观察接口 |
| [Chrome DevTools Page](https://chromedevtools.github.io/devtools-protocol/tot/Page/) | 页面观察与截图接口 |

另已核对本机 `roami chrome help`，Browser Driver 先复用其现有命令。

## 本项目提出的选择

数据表、服务代码层次、SQLite 单写队列、中文双字词检索、任务回报 CLI、提示版本与 cache epoch、SLO 和容量参数均为本项目候选设计，不是声称这些官方框架已采用同一实现。

本地仓库初轮核对基线为 `6907b15`。已有 CLI 与本机 IM 插件的能力通过 help 与源码读取得出；本轮没有调用发送消息的命令，也没有启动真实编码 Agent。

## 统一 CLI 对齐轮

本轮源码基线 `a27f13a`（#328），参考 [统一 CLI v4](../../20261017-CLI统一设计/index.html) 与 `docs/development/session-cli.md`。核对根 `go.mod`、`cmd/roami/api-command.go`、`cmd/roami/database.go`、`internal/storage/layout.go`、`metadb.go`、`backup-set.go`、`backend/ttmux/client.go` 及 `backend/worktree/remote-base.go`。以实际代码区分已存在能力与拟新增 Agent 适配；当前数据库备份不包含 Agent 产物文件。
