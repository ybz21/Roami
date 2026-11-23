# 三平台原生终端调研与设计

采用 **Roami 自有 Go 宿主 `roami-sessiond` + macOS/Linux 的 `creack/pty v1.1.24` + Windows 首选 `crosspty v1.2.0`（ConPTY + PowerShell 7）**。浏览器继续用 xterm.js。服务端屏幕状态先用 `charmbracelet/x/vt v0.1.0` 验证，合入前评估 Go 1.24.2 与回放结果。

开工先将 tmux 接入 `SessionBackend`，再做 Linux 单窗格宿主，随后验 macOS。Windows 并行用 crosspty 做 PowerShell 真机探针。若 Job 清理、退出取证或关闭排空无法通过，回退到 `x/sys/windows` 直接调用 ConPTY。

- [调研与选型（HTML）](index.html#recommended-stack) 给出方案优劣、采用的技术栈和回退条件。
- [产品设计（HTML）](product.html) 说明终端接管、重连和旧会话体验。
- [架构图（HTML）](tech.html#layers) 画出两层接口和平台分支。另有[矢量原图（SVG）](terminal-architecture.svg)。
- [tmux 迁移清单（HTML）](capabilities.html) 映射能力、宿主契约及试点缺失时的行为。
- [Windows 整包移植（HTML）](windows.html) 记录 Go 候选约束、系统调用差异、PowerShell 和 Agent 启动验收。
- [验证记录（Markdown）](acceptance.md) 保留已跑探针、整包构建回执和评审对应项。

代码基线为 Roami `6108a657`。修订参考 [11 月 21 日设计评审](https://github.com/ybz21/Roami/pull/1023#issuecomment-7062408930)与 [11 月 23 日复审](https://github.com/ybz21/Roami/pull/1023#issuecomment-7095594865)。
