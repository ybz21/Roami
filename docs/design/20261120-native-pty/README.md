# 三平台原生终端调研与设计

推荐一套原生 Go 会话宿主和一个 Roami 自有的终端接口。macOS 和 Linux 在接口底层复用 `creack/pty`，Windows 实现同一接口，通过 `golang.org/x/sys/windows` 调用系统 ConPTY，默认启动 PowerShell 7。会话、日志、屏幕捕获和重连逻辑由三平台共用。

- [调研与选型（HTML）](index.html) 给出选型对比、支持范围和迁移顺序。
- [产品设计（HTML）](product.html) 给出用户故事与可展开的场景原型。
- [技术设计（HTML）](tech.html) 给出代码落点、进程生命周期、屏幕恢复和回滚规则。
- [验证记录（Markdown）](acceptance.md) 列出本次实际检查与后续验证范围。

基线为 Roami `6108a657`，日期为 2026-11-20。本文为设计提案。
