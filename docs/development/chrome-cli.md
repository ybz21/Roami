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
