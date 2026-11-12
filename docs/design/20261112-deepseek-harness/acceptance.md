# 验收记录

本任务使用独立 worktree 与 `scripts/dev/isolated-roami.sh /tmp/roami-deepseek-ui` 的私有 tmux 实例。系统的 Roami 服务和 DSH 全局安装未替换。

## 自动检查

- Go：注册描述、未知包元数据、DeepSeek 标准输入、引号与换行、成功与失败退出、拒绝持久启动、npm 安装升级来源与注册 API。
- Python：动态执行器协议、主机 catalog 能力控制持久性，并以 `future-harness` 验证没有新增静态白名单。
- 前端：共享元数据请求、节点隔离、未来 harness 的启动、动态选择器、冷启动命令表单与原有行为回归。

| 检查 | 结果 |
| --- | --- |
| `scripts/dev/quality/check.sh quick` | 通过，含 Go 全量、Python 同步/lint/format/全量测试、前端 typecheck/i18n/hover、密钥与文件检查 |
| Python 全量 | 4,887 passed、48 skipped、6 subtests passed，耗时 1,641.91 秒 |
| 最终 `go test ./...` | 通过；日志 `/tmp/deepseek-go-verified.log` |
| 前端全量 | 234 个测试文件、1,709 项通过；日志 `/tmp/deepseek-vitest-verified.log` |
| 前端生产构建 | 通过；日志 `/tmp/deepseek-build-verified.log` |
| 新增图标/符号审计、`git diff --check` | 新增违规符号 0；无空白错误 |

一次额外 Go 全量复跑中，既有 `TestClaudeCompactionPreservesAuthenticatedTurn/same-prompt` 出现 `SESSION_STOP_UNCONFIRMED`。同代码三次定向复验、完整 `agentexecution` 模块复验及最终 Go 全量均通过。保留 `/tmp/deepseek-go-final.log`、`/tmp/deepseek-compaction-recheck.log` 和 `/tmp/deepseek-agentexecution-recheck.log`。

## 浏览器与真机

桌面覆盖 1280、1920、2560、3440 CSS px；校验文档边界、卡片列表、详情与选择操作。Android 使用 Redmi Note 8，经 LAN 自签 HTTPS 访问私有实例；确认 `compact` / `coarse`、触摸打开详情与页面无横向溢出。最终包重新加载后，DeepSeek 命令为 `dsh --profile headless --permission-mode danger-full-access`。实际 ADB 点按命令框打开 314px 软键盘，输入框保持可见；收键盘后点返回栏正常返回目录。真实触摸滚动将目录 `scrollTop` 从 0 移至 450.18，文档保持 392px 宽、766px 高，无横向溢出。桌面新建会话列出“不启动”与后端五种 Agent，DeepSeek 可选择。另验证英文与浅色主题。

终端工作区在四个桌面宽度分别打开、关闭文件检查器，共 8 个状态；验证终端有效高度、文档边界，以及菜单展示 DeepSeek 的单次任务限制。`desktop.json`、`workspace.json`、`desktop-interactions.json`、`phone.json`、`phone-interactions.json` 和 `phone-scroll.json` 保存测量。

截图：`desktop-before.png` / `desktop-after.png`、`phone-before.png` / `phone-after.png`、`desktop-task-selector.png`、`desktop-terminal-menu.png`、`desktop-en-light-after.png`、`phone-detail-after.png` 与 `phone-keyboard.png`。

同一后端分别提供 HEAD 基线与本次生产前端，1920×1080 各观察 10 秒。元数据请求从无变为每页一个共享 `/agent/registry` 请求；未增加逐 Agent 轮询。TaskDuration、ScriptDuration、JS heap 与请求明细记录在 `production-metrics.json`。短窗口并行测试结果不用于宣称 CPU 或内存降低。

## 验证范围

实际运行了官方 DSH 的版本与帮助命令；适配器的任务执行、成功/失败和参数边界使用本地测试进程验证。没有为 DSH 配置模型或凭据，没有发起 DSH 模型推理，也没有把命令检查冒称真实模型任务成功。


在临时 Node.js 24 与官方 DSH 安装目录加入子进程 PATH 后，真实 `roami agent execution catalog` 回执包含 `kind=deepseek`、`installed=true`、`interactive=false`。记录为 `registered-cli-catalog.json`，版本与帮助输出为 `dsh-version.txt`、`dsh-headless-help.txt`。临时 PATH 不改变系统安装。

验收结束后已关闭本次浏览器标签、两个测试监听端口、记录的私有 tmux 实例，并删除临时 DSH/Node 安装与测试生成的字节码目录。保留截图、日志与测量文件供复查。

## 版本与品牌图标补充验收

安装与升级统一使用 `@deepseek-ai/dsh@latest`，由 npm 在执行时解析发布标签；没有固定版本号。`npm pack --dry-run @deepseek-ai/dsh@latest --json` 成功，当前解析结果记录在 `/tmp/deepseek-latest-package.json`，不作为应用的版本约束。

公共 `AgentLogo` 使用官方 Harness 的鲸鱼 SVG，路径与固定上游提交逐字比对一致，并保留 MIT 许可。创建任务和能力目录继续读取后端注册列表；桌面两处均显示品牌图标，任务选择成功。深色填充为 `rgb(230, 237, 243)`，浅色为 `rgb(31, 35, 40)`，由主题 token 决定。

Redmi Note 8 经 LAN HTTPS 再验收能力目录与顶部“新会话”入口，真实触摸选中 DeepSeek；两处图标存在，文档宽度与视口均为 392 CSS px。未提交测试任务。回执为 `logo-desktop.json` / `logo-phone.json`；截图为 `desktop-logo-after.png`、`desktop-logo-light-after.png`、`desktop-task-logo-after.png`、`phone-logo-after.png`、`phone-task-logo-after.png`，均位于 `/tmp/roami-deepseek-evidence/`。

补充修改通过 Agent 与安装清单 Go 测试、注册与执行契约测试；前端 typecheck、i18n、hover、1,709 项测试与生产构建全部通过，日志前缀 `/tmp/deepseek-followup-`。本轮未修改 Python，沿用上述全量验收。
