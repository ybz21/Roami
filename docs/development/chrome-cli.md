# 浏览器 CLI 开发

正式入口为 `roami chrome`。`backend/browser/automation` 保存 Playwright 驱动与过渡 Bash launcher，通过 Go embed 一起编入 Roami；不需要独立 chrome 业务 CLI。

| 文件 | 职责 |
|---|---|
| `driver.mjs` | Playwright over CDP、标签选择、截图与录制 |
| `scoped-cdp.mjs` | 按目标页连接，隔离无关页面的初始化阻塞 |
| `launcher.sh` | 依赖准备、共享 Chrome 配置、daemon 与 CDP 连接 |
| `process.go` | 嵌入资源、内容版本缓存与子进程启动 |

```bash
go build -o /tmp/roami ./cmd/roami
/tmp/roami chrome help
/tmp/roami chrome setup
/tmp/roami chrome tabs
/tmp/roami chrome screenshot /tmp/check.png --full
```

帮助不创建运行时缓存、不启动 Chrome、不安装依赖。实际自动化需要 Node ≥18、npm、playwright-core ≥1.61、ws 和 Chrome；复用 CDP 时不下载 Playwright 自带浏览器。

默认复用 Web 控制台同一 CDP/profile，正式数据根跟随统一路径解析，兼容旧环境变量。`screenshot --fresh --goto <url>` 使用独立临时浏览器，适合不依赖登录态的验证。

`scripts/build/build-chrome.sh` 仅生成 `exec roami chrome` 兼容启动器，不再复制驱动实现。安装器也可将旧 chrome 命令名链接到同一 Roami 二进制。

## 按目标页连接

`capabilities`、`tabs`、空白 `new` 直接通过浏览器级 CDP 查询或创建，不初始化现有页面。
页面操作使用 Playwright 的公开 `connectOverCDP(transport)` 接口：根会话的自动附着排除所有目标，
再显式附着本次选中的 target；目标页内 iframe 的自动附着保持原协议。无关页面不会被调试暂停或等待初始化。
切换目标时复用各目标的连接，保留截图视口会话及录制状态，避免断开会话让镜像 DPR 重置。
已关闭目标在下次标签读取或操作时回收，浏览器身份变化时清理旧连接；daemon 空闲退出时关闭全部连接。关闭连接不会关闭共享 Chrome。

启动器检查依赖版本并按需升级到 Playwright ≥1.61 和 ws ≥8.18；新驱动使用带 `.scoped-v2` 后缀的
独立 daemon socket，避免复用已加载旧代码的进程，不终止其动作。连接就绪检查仍有时限，页面操作不因连接失败自动重放。

## 稳定目标与单次调用

`tabs` 和 `new` 的 JSON 回执包含 `targetId`。Agent 保存这个 ID，并使用 `--target <targetId>`；它与 `--tab`、`--url` 互斥。每次调用通过临时 CDP 会话解析实际 page，标签关闭后明确返回 `CHROME_TARGET_NOT_FOUND`，不会回退到首个标签。临时会话在成功或失败后都会断开。这遵循 [CDP Target](https://chromedevtools.github.io/devtools-protocol/tot/Target/) 与 [Playwright CDP session](https://playwright.dev/docs/api/class-browsercontext#browser-context-new-cdp-session) 的接口。

```bash
roami chrome tabs --no-retry
roami chrome fill '#title' 'example' --target <targetId> --no-retry
```

`--no-retry` 限制 daemon 请求为一次，包括连接失败和响应丢失；不把未知写结果重新执行。稳定目标或单次调用使用带版本边界的内部动词封装，旧 daemon 会在执行动作前拒绝该动词，防止它忽略新选项而操作错误标签。CLI 不会为升级而杀掉已有 daemon；等待其空闲退出或使用独立 socket 后重试。该选项不证明取消 CLI 就停止了 daemon 中的动作，Agent 仍需持久化动作回执和资源对账。

`go test ./backend/browser/automation` 会运行 Node 原生契约测试。真实浏览器验证使用独立 profile/CDP/socket，不操作用户浏览器。

## 资源回收与截图视口

导航临时开启的 TLS CDP 会话在导航成功或失败后释放；新建标签导航失败时关闭本次创建的标签，避免重试积累空页。

CDP 截图每个标签复用一个会话，关标签时释放。尺寸、设备和整页截图会在 `finally` 中恢复渲染视口、DPR 和屏幕尺寸；设备截图同时恢复 UA 与触摸状态。不能在恢复后直接断开这个会话：真实 Chrome 会再次重置 DPR，影响仍在观看的镜像。普通 Playwright 截图失败后的 CDP 降级也遵循同一回收规则。

## 持久化动作回执

自动化动作可带 `--operation-id <32位小写十六进制ID> --receipt-root <私有绝对目录>`。CLI 先持久化接收记录，再向 daemon 提交一次。相同 ID / 参数返回已有回执，参数变化拒绝；daemon 使用持久化独占执行标记，进程死亡也不会重新执行。`eval`、`record`、`--fresh` 不支持此模式，以免把跨调用的后台行为误认成一次已停止的动作。

```bash
roami chrome click '#confirm' --target <targetId> --operation-id <operationId> --receipt-root <receiptRoot>
roami chrome operation-status --operation-id <operationId> --receipt-root <receiptRoot>
roami chrome operation-cancel --operation-id <operationId> --receipt-root <receiptRoot>
```

status / cancel 不连接或启动 Chrome；目录必须为当前用户私有。取消先保存取消标记：未开始的动作可立即确认取消，运行中的动作须等待真实回执。`inputStopped` 表示该驱动不再继续输入，`outcomeKnown` 表示动作效果是否明确，两者分开；异常可以已停止但效果未知。此模式输出回执 JSON，调用方必须检查 state，不能用 CLI 的退出码判断业务目标完成。错误只保存稳定机器码，文件损坏或缺失不触发重放。升级不杀正在执行动作的旧 daemon，版本动词让不支持协议的 daemon 在动作前拒绝。

## 场景观察与动作前校验

`capabilities` 返回驱动能力与实际 CDP 连接所绑定的 browserId。实例身份取自 [Chrome 官方发现接口](https://chromedevtools.github.io/devtools-protocol/index.html#how-do-i-access-the-browser-target) `/json/version` 的浏览器 WebSocket 端点；不能拿每个根 CDP 会话分配的 targetId 当浏览器身份。相同端口换了 Chrome 时会重新连接，动作不会落到仍缓存的另一实例上。

`observe --target <id>` 返回有界主框架文本、可见控件、viewport/DPR、时间与场景签名。原始 DOM、用于签名的完整输入集合和焦点细节不回传；可见控件值受长度上限约束，密码控件的值隐藏。超出输出预算的控件明确标记截断，跨 iframe 的内容不冒充主框架观察。可选 `--screenshot <新文件.png>` 返回图片尺寸和 viewport 到像素的比例；截图前后场景不同则丢弃混合观察。

动作带 `--expected-browser <browserId> --expected-scene <signature>` 时，先验证实例和页面状态再输入。焦点检查发生在前置标签之前，避免先抢回焦点再漏掉人工切换。表单值、选区、viewport/缩放、焦点或 DOM 变化会使完整页面签名失效。`observe` 另返回 `navigationSignature`：仅 `goto` 可使用它，校验浏览器、标签、文档、URL、输入内容、焦点和选区，允许广告或正文自动更新；点击、输入等动作仍必须使用完整 `signature`。此模式使用新的内部版本动词，旧 daemon 不会忽略校验选项后继续动作。动作返回仍需再次观察和任务验收，不等于用户目标完成。
