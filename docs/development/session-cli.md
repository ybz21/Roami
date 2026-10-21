# 会话 CLI 开发

应用由根 Go module 构建，正式入口为 `roami session`。会话 CLI 和 Web 共用 `internal/application`、`internal/session`、`internal/tmuxruntime` 与 `internal/storage`，不再发布另一套会话业务引擎。

```bash
go build -o /tmp/roami ./cmd/roami
/tmp/roami session help
/tmp/roami session ls --json
go test ./...
```

`internal/cli` 保留参数解析和终端输出，`internal/application` 提供结构化会话用例；新增能力先实现共享业务接口，再接 CLI/HTTP 适配。交互式 attach 保留直接 tmux 终端行为。

公共入口统一为 `roami session`。`ttmux` 可执行名与 `roami ttmux` 已退役；安装器把旧链接、旧 Bash 备份和旧辅助脚本移入配置备份根下的 `cli-entry-migration/`，不在 PATH 中保留第二套实现。会话 ID、数据库、旧路径读取和协议标识不随 CLI 改名而重写。

未知命令直接报错，不再转发原生 tmux。`roami session keys <会话> <按键...>` 仅接受具名方向键、回车、中断及单个字母数字，与 HTTP 按键接口复用校验。公共入口不提供全局关闭或加载原生配置命令；必要的窗格查询、按键注入由后端内部适配器调用。原生 tmux 仍是运行底座。需要系统级隔离时，智能体须使用独立用户或容器并经受控服务访问；同一用户的任意 shell 不能仅靠 CLI 改名获得权限隔离。

## 隔离验证

```bash
scripts/dev/isolated-roami.sh /tmp/roami-check /tmp/roami session ls --json
scripts/dev/isolated-roami.sh /tmp/roami-check --stop
```

隔离启动器固定存储根与独立 tmux socket，覆盖继承的 `TMUX`、`TMUX_BIN` 和 `TTMUX_BIN`，记录 server PID 与实例标记。`--stop` 仅清理此目录记录的 tmux server，拒绝篡改的 socket、PID 或实例标记；它不停止另行后台启动的 Web/Agent 进程，完整验收实例的进程由 `scripts/dev/agent-acceptance/instance.py --stop` 校验并停止。

不要只改 `TMUX_TMPDIR` 后清理；不要手写未核对目标的全局停止命令。禁止在用户实际数据库上测试迁移。回归使用两个一次性 server，模拟主实例在测试清理后仍须存活。

新任务 worktree 每次成功 fetch 后固定远端 OID；失败返回错误，既有任务分支不自动 reset/rebase。Go 回归在 `backend/worktree/remote-base_test.go`。

端到端验收：`ROAMI_BIN=/tmp/roami bash tests/test-session-cli.sh`，覆盖创建、派生、改名、输入提交、读取及明确目标关闭；拒绝全局停止和原生命令后，已有测试会话仍然可访问。旧入口迁移的回归为 `scripts/dev/selftest/retired-session-entries.sh`。
