# 原生终端调研验证记录

2026-11-20，Roami 基线 `6108a657`，验证节点为 Linux amd64，Go 1.24.0。

## 本次实际检查

| 检查 | 结果 |
| --- | --- |
| Roami 代码走读 | 确认 WebSocket 启动的是外层 `tmux attach`，shell 与 Agent 的进程归 tmux server。定位会话身份、输入围栏、屏幕读取、日志、恢复与发布入口。 |
| Linux 独立 PTY 实跑 | 项目现有的 `creack/pty v1.1.24` 直接启动 `/bin/sh`，子进程的 stdin / stdout 确认为 TTY。初始 80×24，在线改为 132×32，双向输入、中文输出和退出码 7 均通过。用 `scripts/dev/isolated-roami.sh` 启动试验并通过同入口 `--stop` 清理。 |
| macOS 交叉编译 | 同一 PTY 探针用 `CGO_ENABLED=0` 编译出 darwin/arm64 与 darwin/amd64 的 Mach-O。 |
| Windows 交叉编译 | 用现有 `golang.org/x/sys v0.41.0` 对 ConPTY、进程启动和 Job Object 类型与 API 做编译探针，产出 windows/amd64 与 windows/arm64 的 PE。 |
| Windows 整包基线 | `CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build ./cmd/roami` 已执行，编译止于现有 Unix 调用。会话生命周期、存储、浏览器标签和 Agent 注册依赖 `Flock`，内存守护依赖 `Statfs`，宿主监控和手机模拟器有 `Setsid`、`Setpgid` 或 `Kill` 等调用。 |
| Chrome 打开产物 | 打开调研、产品和技术三页，核对相对链接和样式加载，并点击展开产品场景。检查了桌面和 390px 窄视口。 |
| 上游源码与文档 | 查阅 Microsoft ConPTY、Job Object、PowerShell 文档与候选库源码。核对了 Go 版本、原生 API 和候选库的启动、关闭边界。 |

探针交叉编译验证的是编译产物和符号可用性。平台适配器、Go 会话宿主和整包 Windows 启动属于下一阶段。

## 2026-11-21 评审补测

| 检查 | 实际结果 |
| --- | --- |
| crosspty v1.2.0 / Go 1.24 | Linux amd64 实跑控制 TTY、双向读写、80×24 到 132×32、中文、退出前尾部输出、退出码 7、显式关闭。子进程退出后继续读，收到 EOF。 |
| go-pty v0.2.3 / Go 1.25 | 用相同 Linux 探针实跑交互、尺寸、中文、尾部输出和退出码 7。首次探针等待退出后读到 EOF 超时。分步复跑确认进程已退出，额外读等待 1 秒仍阻塞，显式关闭可完成。库在 Unix 保留 slave 句柄至关闭，因此两种候选的 EOF 用法需要分别适配。 |
| 两种候选的交叉编译 | 各自独立 Go 模块，`CGO_ENABLED=0` 编译通过 darwin/arm64、windows/amd64、windows/arm64。未变更仓库的 `go.mod`。编译验证未覆盖 macOS 或 Windows 的运行行为。 |
| Zellij v0.44.3 / Linux | 独立 socket 与数据目录下，CLI 创建分离会话、开窗格、按 pane ID 送文本和 Enter、`dump-screen` 取得回显。原生 Windows 能力来自上游发行记录，未在 Windows 运行。 |
| 隔离清理 | Linux 探针经 `scripts/dev/isolated-roami.sh` 启动，测试实例经同入口 `--stop` 清理。Zellij 只停止并删除试验会话。 |
| Windows 整包基线 | 在本次评审中重跑交叉构建，仍出现下列七个包的编译阻塞。 |

库的优先顺序用于安排下一轮 Windows 真机验证。采用哪一种还需通过 [Windows 整包验收](windows.html#go-no-go)。[go-pty Unix 句柄管理](https://github.com/aymanbagabas/go-pty/blob/v0.2.3/pty_unix.go)

## Windows 整包编译回执

命令为 `CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -o <临时目录>/roami.exe ./cmd/roami`，退出码 1。以下为每个阻塞包的首条报错。

```text
internal/browsertabs/catalog.go:115:16: undefined: unix.Flock
internal/sessionlifecycle/worker.go:26:19: undefined: syscall.LOCK_EX
internal/memguard/memguard.go:249:25: undefined: syscall.Statfs_t
plugins/hostmonitor/swap.go:196:41: unknown field Setsid in struct literal of type syscall.SysProcAttr
internal/agentproviders/store.go:36:10: undefined: unix.Flock
backend/phone/android_avd.go:267:41: unknown field Setsid in struct literal of type syscall.SysProcAttr
internal/storage/layout.go:139:14: undefined: unix.LOCK_SH
```

同批回执中还有 `syscall.Flock`、`syscall.Statfs`、`Setpgid` 和 `syscall.Kill` 等错误。上述包先编译通过后再重跑，继续定位依赖它们的后续报错。

## PR 评审落实

| 评审项 | 设计调整 |
| --- | --- |
| P0 宿主托管和升级 | [独立最小宿主、路由与排空](tech.html#supervision)；纳入双版本接回旧窗格、协议错配和围栏验收。 |
| P0 tmux 耦合 | [能力迁移清单](capabilities.html)；覆盖内存、活跃度、Capture、日志、受管提交和分屏。 |
| P0 Windows 范围 | [独立整包移植说明](windows.html)；明确候选库退出语义、文件锁、启动器、用户身份和发版条件。 |
| P0 手机尺寸与控制 | [接管模型](product.html#control)；首个真实键入或点按接管，尺寸跟随宿主，窄屏保留字号。 |
| P1 VT、协议、进程和隔离 | [试点验收](tech.html#acceptance) 与 [连接协议](tech.html#protocol)；分开 PTY 和任务证据，明确双实例、重放和后续规则落点。 |
| P2 资料结构 | 选型、Unix 试点、Windows 移植分开，验证入口改为 HTML 页内锚点，保留 Markdown 原始回执。 |

## 实现阶段验收

| 范围 | 场景与通过条件 |
| --- | --- |
| 三平台原生 PTY | Linux amd64 与 arm64、macOS arm64 与 amd64、Windows 首发版本 x64 再到 arm64。验证交互 shell、TTY/控制台判定、含空格和中文的 cwd / argv / env、初始尺寸、动态调整、Ctrl+C、退出码。Windows 重点验 PowerShell 7、PSReadLine、ConPTY 排空和 Job Object；两种 Windows 架构的发布声明以各自实测为准。 |
| 终端一致性 | 同一窗格在 CLI、桌面与 Android 真机中验证中文、分块 UTF-8、备用屏、光标、鼠标/翻页、粘贴、Shift+Enter、后台和旋转。用 shell、vim、Codex、Claude Code 在支持的平台对照现有实现，至少覆盖一次运行中重连与一次已退出后的捕获。按 Roami Web UI 验收规程检查移动交互。 |
| 进程与恢复 | Web 服务重启、宿主软件滚动升级后，既有会话的窗格代次和 OS 进程身份保持一致，新建走新宿主，旧宿主排空后才停止。宿主崩溃、输出堵塞、权限错误、半启动、PID 复用时正确区分未知与确认退出，证据完整才释放围栏。并发创建/停止只对目标会话生效，重连和超时均不重复投递输入。 |
| 发版与回滚 | 同实例验证 tmux 旧会话和原生会话并存，切换默认项后两者均可按原归属附着。回滚使用兼容两种后端的版本。分别验证 Windows 的安装、更新及用户身份，CI 交叉编译与真实运行均通过。 |
| 性能基线 | 在同一主机和输出负载下，用 1、10、30 个会话对照旧链路与原生链路。记录首屏和重连 P50/P95、输入到回显延迟、空闲/繁忙时 CPU 与 RSS、句柄和 goroutine 数。让一个客户端停止读取，其他订阅者和窗格应继续运行，恢复时画面不重复或缺段。 |

<https://github.com/ybz21/Roami/blob/6108a657/docs/development/web-ui-checklist.md>
