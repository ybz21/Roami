# 浏览器 CLI 开发

正式入口为 `roami chrome`。`backend/browser/automation` 保存 Playwright 驱动与过渡 Bash launcher，通过 Go embed 一起编入 Roami；不需要独立 chrome 业务 CLI。

| 文件 | 职责 |
|---|---|
| `driver.mjs` | Playwright over CDP、标签选择、截图与录制 |
| `launcher.sh` | 依赖准备、共享 Chrome 配置、daemon 与 CDP 连接 |
| `process.go` | 嵌入资源、内容版本缓存与子进程启动 |

```bash
go build -o /tmp/roami ./cmd/roami
/tmp/roami chrome help
/tmp/roami chrome setup
/tmp/roami chrome tabs
/tmp/roami chrome screenshot /tmp/check.png --full
```

帮助不创建运行时缓存、不启动 Chrome、不安装依赖。实际自动化需要 Node、npm、playwright-core 和 Chrome；复用 CDP 时不下载 Playwright 自带浏览器。

默认复用 Web 控制台同一 CDP/profile，正式数据根跟随统一路径解析，兼容旧环境变量。`screenshot --fresh --goto <url>` 使用独立临时浏览器，适合不依赖登录态的验证。

`scripts/build/build-chrome.sh` 仅生成 `exec roami chrome` 兼容启动器，不再复制驱动实现。安装器也可将旧 chrome 命令名链接到同一 Roami 二进制。

## 稳定目标与单次调用

`tabs` 和 `new` 的 JSON 回执包含 `targetId`。Agent 保存这个 ID，并使用 `--target <targetId>`；它与 `--tab`、`--url` 互斥。每次调用通过临时 CDP 会话解析实际 page，标签关闭后明确返回 `CHROME_TARGET_NOT_FOUND`，不会回退到首个标签。临时会话在成功或失败后都会断开。这遵循 [CDP Target](https://chromedevtools.github.io/devtools-protocol/tot/Target/) 与 [Playwright CDP session](https://playwright.dev/docs/api/class-browsercontext#browser-context-new-cdp-session) 的接口。

```bash
roami chrome tabs --no-retry
roami chrome fill '#title' 'example' --target <targetId> --no-retry
```

`--no-retry` 限制 daemon 请求为一次，包括连接失败和响应丢失；不把未知写结果重新执行。稳定目标或单次调用使用带版本边界的内部动词封装，旧 daemon 会在执行动作前拒绝该动词，防止它忽略新选项而操作错误标签。CLI 不会为升级而杀掉已有 daemon；等待其空闲退出或使用独立 socket 后重试。该选项不证明取消 CLI 就停止了 daemon 中的动作，Agent 仍需持久化动作回执和资源对账。

`go test ./backend/browser/automation` 会运行 Node 原生契约测试。真实浏览器验证使用独立 profile/CDP/socket，不操作用户浏览器。

## 持久化动作回执

自动化动作可带 `--operation-id <32位小写十六进制ID> --receipt-root <私有绝对目录>`。CLI 先持久化接收记录，再向 daemon 提交一次。相同 ID / 参数返回已有回执，参数变化拒绝；daemon 使用持久化独占执行标记，进程死亡也不会重新执行。`eval`、`record`、`--fresh` 不支持此模式，以免把跨调用的后台行为误认成一次已停止的动作。

```bash
roami chrome click '#confirm' --target <targetId> --operation-id <operationId> --receipt-root <receiptRoot>
roami chrome operation-status --operation-id <operationId> --receipt-root <receiptRoot>
roami chrome operation-cancel --operation-id <operationId> --receipt-root <receiptRoot>
```

status / cancel 不连接或启动 Chrome；目录必须为当前用户私有。取消先保存取消标记：未开始的动作可立即确认取消，运行中的动作须等待真实回执。`inputStopped` 表示该驱动不再继续输入，`outcomeKnown` 表示动作效果是否明确，两者分开；异常可以已停止但效果未知。此模式输出回执 JSON，调用方必须检查 state，不能用 CLI 的退出码判断业务目标完成。错误只保存稳定机器码，文件损坏或缺失不触发重放。升级不杀正在执行动作的旧 daemon，版本动词让不支持协议的 daemon 在动作前拒绝。
