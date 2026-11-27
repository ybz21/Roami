# 原生终端：实验记录与验收清单

基线：`6108a657` · 试验机：Linux amd64，Go 1.24.0。

## 已跑实验

| 项目 | 结果 |
| --- | --- |
| Linux PTY（`creack/pty v1.1.24`） | 跑 `/bin/sh`：真 TTY、80×24→132×32、中文、退出码 7 全过；`isolated-roami.sh` 清理。 |
| `crosspty v1.2.0`（Go 1.24） | Linux 同套全过，退出后继续读正常 EOF。 |
| `go-pty v0.2.3`（Go 1.25） | 交互和退出码过，但退出后再读阻塞（Unix 留着 slave 句柄至 Close）。 |
| 交叉编译探针 | `CGO_ENABLED=0` 编过 darwin/windows 的 amd64/arm64（未动仓库 `go.mod`，未真机跑）。 |
| Zellij v0.44.3（Linux） | 跑通新建/分屏/送键/`dump-screen`，仅作对照。 |
| Windows 整包试编 | `GOOS=windows GOARCH=amd64 go build ./cmd/roami` 拦在 7 个包（见下）。 |
| SQLite 并发事务模型 | 验证单次 CAS 切换、过期拒收、跨代防重、2 代排空上限与回滚代次递增。 |
| 文档页面检查 | Chrome 验亮/暗色、桌面与 390px 窄屏、SVG 架构图与链接。 |
| 核心实现首轮验收（2026-11-23） | 落地 `internal/terminal`（Unix PTY + Windows 原生 ConPTY/Job）、`internal/sessionbackend`（接口 + 二叉树分屏 + 双后端路由）、`internal/sessionhost`（`session-host.db` + 服务端 VT/DSR 秒回 + 窗格/分屏）、`internal/sessionipc`（`yamux` + 脱壳拉起 + Manager）、`cmd/roami-sessiond`、`sessmeta` 分宿主对账/启动批次休眠与 `backend/pty/native.go` WS 桥接；10 个包 `-race` 全绿，双独立 `roami-sessiond` 实例隔离实测通过，`cmd/roami-sessiond` 经 `CGO_ENABLED=0` 交叉编译通过 Linux/macOS(arm64,amd64)/Windows(amd64,arm64) 5 个目标。 |

| Windows 整包编译（2026-11-25） | 抽离跨平台原语 `internal/filelock`、`internal/procctl`、`internal/fsguard` 并隔离平台文件（`memguard`、`agentruntime`、`okr`、`pty`、`api`），清零全仓库 Unix 强耦合；`CGO_ENABLED=0` 交叉编译 `cmd/roami` 与 `cmd/roami-sessiond` 全过 `windows/amd64`、`windows/arm64`、`darwin/arm64`、`darwin/amd64`、`linux/amd64` 五个目标（含前端 `SplitTree` 与 `ROAMI_NATIVE_TERMINAL=1` 灰度入口）。 |

## Windows 整包编译回执

初期基线 `CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./cmd/roami` 曾拦在 `browsertabs`、`sessionlifecycle`、`memguard`、`hostmonitor`、`agentproviders`、`phone`、`storage` 及上层 `okr`/`modelgateway`/`worktree`/`agentexecution`/`pty`/`api`/`cmd/roami` 的 `Flock`、`SysProcAttr`、`Kill`、`Stat_t`、`O_NOFOLLOW`、`creack/pty` 调用。

现已全部收敛为三组跨平台原语与最小平台文件，实测五目标编译全过（0 报错）：

```text
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./cmd/roami ./cmd/roami-sessiond  # OK
CGO_ENABLED=0 GOOS=windows GOARCH=arm64 go build ./cmd/roami ./cmd/roami-sessiond  # OK
CGO_ENABLED=0 GOOS=darwin  GOARCH=arm64 go build ./cmd/roami ./cmd/roami-sessiond  # OK
CGO_ENABLED=0 GOOS=darwin  GOARCH=amd64 go build ./cmd/roami ./cmd/roami-sessiond  # OK
CGO_ENABLED=0 GOOS=linux   GOARCH=amd64 go build ./cmd/roami ./cmd/roami-sessiond  # OK
```

## 实现验收清单

| 范围 | 过关标准 |
| --- | --- |
| 三平台 PTY | Linux / macOS / Win11 24H2+（x64 再 arm64）：登录 shell、真 TTY、空格/中文路径、启动期传 `Env`、缩放、Ctrl+C、退出码；Windows 验 PSReadLine、`ESC[6n` DSR 秒回、收尾与 Job 清理；CI 跑三平台编译门禁。 |
| 终端体验 | CLI / 桌面 / Android 同连一窗格：中文、跨块 UTF-8、备用屏、含历史滚动快照、`move-cursor` 不误吞暗/灰建议、服务端唯一答查询、鼠标/翻页/粘贴/Shift+Enter、窄屏只看左右滑不撞手势、转屏。覆 shell/vim/Codex/Claude Code，过 [web-ui-checklist.md](../../development/web-ui-checklist.md)。 |
| 升级与恢复 | 重启 Web、宿主滚动升级（主库 `meta.db` 迁移期间老宿主稳定）不断线；按宿主分片对账，整机重启不漏休眠；异常或 PID 复用绝不误放围栏；重连/超时不重发输入。 |
| 并发与排空 | 同 `operation_id` 并发只建一个窗格；并发升级仅一次 CAS 成功；协调数据全在 `session-host.db`；2 代排空上限拦截新升级，宿主真退无引用才删二进制。 |
| 灰度与性能 | tmux 与原生并存，切默认/回滚只影响新建；1/10/30 会话（各 5000 行历史）对照首屏/打字延迟与 CPU/内存；卡死单个慢客户端不影响他人。 |
