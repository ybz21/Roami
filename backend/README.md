# Roami Web 服务端

Web 服务、会话核心和 CLI 共用仓库根目录的一个 Go module：`github.com/ybz21/Roami`。
服务端通过进程内 application/session 核心管理会话；终端桥接仍调用原生 tmux。
CLI 的正式入口为 `roami session`、`roami chrome`、`roami project`、`roami auth`、`roami db`。

从仓库根目录运行：

```bash
./start.sh --dev
go build -o /tmp/roami ./cmd/roami
/tmp/roami server -addr 127.0.0.1:8080 -web frontend/dist
```

完整自包含构建使用 `scripts/build/build-roami.sh`，前端构建后嵌入正式二进制。
分离开发时，在另一终端运行 `cd frontend && npm run dev`。

配置默认位于 `~/.roami/config.yaml`，schema 见
[`config.yaml.template`](../configs/config.yaml.template)。存储路径支持 `ROAMI_HOME`、
`ROAMI_DATA`、`ROAMI_DATABASE_DIR`、`ROAMI_BACKUP_DIR`；默认数据库位于
`~/.roami/database/`。旧布局必须先停写，再用 `roami db migrate --layout --dry-run`
盘点、用 `roami db migrate --layout --offline` 显式迁移。

| 目录 | 职责 |
| --- | --- |
| `cmd/roami/`（仓库根） | 统一命令入口、参数与服务启动 |
| `internal/application/`（仓库根） | 会话应用服务 |
| `internal/storage/`（仓库根） | 数据库 schema、布局、清单、锁、备份与恢复 |
| `backend/server/` | HTTP 路由、中间件、回退页 |
| `backend/api/` | API handlers |
| `backend/ttmux/` | 进程内核心适配与旧外部 CLI 兼容 |
| `backend/pty/` | 原生 tmux 与 WebSocket 终端桥接 |
| `backend/auth/` | 认证与访问控制 |
| `backend/browser/automation/` | `roami chrome` 内嵌驱动 |

统一架构和迁移边界见
[CLI 统一设计](../docs/design/20261017-CLI统一设计/index.html)。
