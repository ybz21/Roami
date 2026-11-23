# 三平台原生终端调研与设计

Roami 自己管理会话，底层复用系统 PTY。先抽离 tmux 会话接口，以独立的 Go 宿主试点 Unix 单窗格，Windows 并行验证 `crosspty`、`go-pty` 和直接调用 ConPTY。

- [调研与选型（HTML）](index.html) 比较 PTY 库和 multiplexer，给出首轮决策。
- [产品设计（HTML）](product.html) 说明终端接管、重连和旧会话体验。
- [会话宿主与 Unix 试点（HTML）](tech.html) 包含宿主托管、升级排空、传输协议和实施门槛。
- [tmux 迁移清单（HTML）](capabilities.html) 映射能力、宿主契约及试点缺失时的行为。
- [Windows 整包移植（HTML）](windows.html) 记录 Go 候选约束、系统调用差异、PowerShell 和 Agent 启动验收。
- [验证记录（Markdown）](acceptance.md) 保留已跑探针、整包构建回执和评审对应项。

代码基线为 Roami `6108a657`。修订参考 [11 月 21 日设计评审](https://github.com/ybz21/Roami/pull/1023#issuecomment-7062408930)与 [11 月 23 日复审](https://github.com/ybz21/Roami/pull/1023#issuecomment-7095594865)。
