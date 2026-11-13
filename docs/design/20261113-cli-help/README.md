# CLI 帮助统一与逐级发现

## Product Design

`roami project -h` 原来只有一行命令名，`roami session -h` 使用另一套彩色总览；会话多数子命令没有专属帮助，`fork -h` 甚至会进入真实参数处理。用户无法从同一种阅读习惯理解命令，也无法可靠地逐级发现参数。

统一为“命令与用途、用法、命令或参数、示例、必要说明、进一步帮助”。总览解释每个入口的用途，详细参数归属具体命令。长命令的说明换到下一行，不靠大量手工空格对齐。交互终端只加粗标题，管道、文件及 `NO_COLOR` 输出纯文本。

常规入口支持 `-h`、`--help`、`help ...`、`命令 help`，嵌套到 `session env set`、`swarm member add`、`agent capability market search` 等粒度。`session sp -h` / `split -h` 保留左右分割语义，帮助使用 `--help` 或 `help sp`。已带目标与文本的输入不作为帮助拦截。

ADB 保留系统命令的原生帮助与字节流透传。依赖当前 Agent 上下文的能力按注册路径发现，详情给出 `--input JSON` 与查询 schema 的入口，不伪造宿主身份或增加执行权限。终端输出按 i18n 规范的 shell 输出例外处理，未修改 Web 文案。

## User Stories

1. 查看 `roami project -h` 或 `roami session -h`，能按相同结构找到下一步，而不是猜缩写的用途。
2. 执行 `roami session fork -h`，直接看到必填子会话名称、父会话默认值、目录覆盖、分离模式、JSON 回执与两种示例。
3. 在未初始化实例、缺少 tmux 或未启动服务时也能查询帮助，且不会新建会话、初始化数据库或启动浏览器。
4. 将帮助重定向到文件后仍可读；向会话发送字面 `--help` 及左右分割参数继续有效。

## Technical Design

- `internal/cli/help/page.go`：统一排版及命令边界识别，色彩取决于实际输出 writer 是否为终端。
- `internal/cli/help/session-command.go`：会话及嵌套命令的专属用法，替代“不认识子命令帮助就返回总览”。
- `cmd/roami/help-catalog.go`：原生命令用途、语法、示例；`newCommandFlags` 直接读取真实 flags 注册的参数说明与默认值，并按命令筛选，避免展示不相关参数。
- `cmd/roami/help-groups.go`：分组发现与帮助路由，先于实例租约、配置读取或服务连接；未知帮助主题给出可恢复的提示。
- `cmd/roami/help-terminal.go`：浏览器与插件的原生参数说明；ADB 继续透传。
- `cmd/roami/agent-command-family.go`：复用既有能力注册路径，逐级展示需 Agent 上下文的命令；原生命令优先保留其位置参数形式。
- `internal/cli/swarm/help.go`：蜂群总览与具体操作分开；保留修订、幂等键、验收边界和文件输入说明。
- flags 解析器收到 `flag.ErrHelp` 返回成功；真实参数错误仍返回失败。`server -h` 在配置与存储初始化前输出统一帮助。

## Acceptance

验收命令均通过 `scripts/dev/isolated-roami.sh` 运行；临时二进制与命令截图留在 `/tmp/roami-cli-help/`，不提交主线。

- 自动回归遍历原生命令目录、分组与注册能力路径的四种帮助写法；使用不存在的配置目录、不可达服务和不可用 tmux，检查退出状态、专属标题、统一结构、纯文本输出，以及未初始化存储。
- 会话专项覆盖所有公开操作及 `env`、`parent`、`db` 的嵌套命令；保留 `send SESSION --help`、`fork SESSION --help` 与 `sp -h` 的字面/业务语义。
- 渲染器覆盖纯文本对齐、长命令的说明换行、写出错误及 fork 帮助内容。

实际编译二进制验证 147 个入口、588 次查询，四种帮助形式输出一致，均未创建配置、数据库或会话资源。还验证了未知帮助主题返回 2 与恢复提示。实际隔离会话完成 new、fork、children、rename、resolve、capture、kill；改名后稳定 ID 保持不变。PTY 下标题加粗，`NO_COLOR=1` 下无 ANSI 控制字符。

本机证据：`/tmp/roami-cli-help/verification.json`（JSON 验证报告）、`help-before.png` / `help-after.png`（两组根帮助改前/改后）、`fork-after.png`（子命令帮助）。截图把实际 stdout 原样放进终端文本页面后捕获，已打开核对，不是 Web UI 修改，也未手工重写输出。

首次全仓运行中，既有 `TestSessionCancellationDeniesNewToolsAndWaitsForCompletion` 一次返回 `SESSION_STOP_UNCONFIRMED`；该单项独立连跑三次通过。最终质量门使用 `GOFLAGS=-p=1` 串行运行，生命周期实现与该测试保持原样。

最终 `scripts/dev/quality/check.sh full` 与 `quick` 均通过：Go 全仓测试、CLI/安装审计、Shell/Go 格式、前端 typecheck/i18n/hover、生产构建及压缩、秘密扫描与暂存文件检查。Python 检查按 Go-only 变更计划跳过 runtime/skill 检查，Go 测试原有 Python harness 正常执行。前端构建保留既有大 chunk 提示。

日志保留在 `/tmp/roami-cli-help/quality-full-final.log`、`quality-quick.log` 与 `cli-tests.log`；本任务没有修改前端界面。
