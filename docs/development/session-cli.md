# 会话 CLI 开发

应用由根 Go module 构建，正式入口为 `roami session`。会话 CLI 和 Web 共用 `internal/application`、`internal/session`、`internal/tmuxruntime` 与 `internal/storage`，不再发布另一套会话业务引擎。

```bash
go build -o /tmp/roami ./cmd/roami
/tmp/roami session help
/tmp/roami session ls --json
go test ./...
```

`internal/cli` 保留参数解析和终端输出，`internal/application` 提供结构化会话用例；新增能力先实现共享业务接口，再接 CLI/HTTP 适配。交互式 attach 保留直接 tmux 终端行为。

安装器保留 `ttmux` 命令名作为同一 Roami 二进制的兼容入口。旧命令的 JSON 与会话 ID 保持兼容，用户新指引使用 `roami session`。

## 隔离验证

```bash
scripts/dev/isolated-roami.sh /tmp/roami-check /tmp/roami session ls --json
```

隔离启动器清除旧路径变量并固定全部存储根；真实 tmux 验证另用 `TMUX_BIN` 包装器绑定独立 socket。禁止在用户实际数据库上测试迁移。

新任务 worktree 每次成功 fetch 后固定远端 OID；失败返回错误，既有任务分支不自动 reset/rebase。Go 回归在 `backend/worktree/remote-base_test.go`。
