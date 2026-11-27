# 三平台原生终端：调研与设计

Roami 摆脱 tmux 依赖，用自有独立 Go 宿主 `roami-sessiond` 管三平台原生终端（macOS / Linux 用 `creack/pty v1.1.24`，Windows 首选 `crosspty v1.2.0` 并行对照 `x/sys/windows` 直接调 ConPTY，浏览器继续用 xterm.js）。

- [调研与选型](index.html#recommended-stack) — 选什么、为什么、怎么开干
- [产品设计](product.html) — 第一阶段体验、电脑/手机接管与场景
- [技术设计](tech.html#layers) — 架构图（[SVG](terminal-architecture.svg)）、分层、分屏预留、升级与协议
- [tmux 迁移清单](capabilities.html) — 现有能力替换表与代码收口顺序
- [Windows 整包移植](windows.html) — ConPTY、系统调用适配、PowerShell 与放行门槛
- [验证记录](acceptance.md) — 已跑实验、Windows 编译报错与验收清单

基线：`6108a657` · [PR #1023](https://github.com/ybz21/Roami/pull/1023)
