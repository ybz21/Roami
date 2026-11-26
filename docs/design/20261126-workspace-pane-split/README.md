# 产品层独立窗格分屏（Workspace Pane Split）设计方案

Terminal 保持为完全独立的单一 PTY + 独立 xterm.js 个体，分屏与窗口编排提升到 Roami 产品界面层（DOM 布局树），彻底解决单画布字符分屏导致的跨列误选、跨行复制污染、无法独立全选/滚动与手机端挤压问题。

- [设计总览（index.html）](index.html) — 核心痛点对比、产品层独立窗格架构图与分阶段落地计划
- [产品设计（product.html）](product.html) — 交互原则、复制/全选/滚动/焦点/关闭体验、桌面与手机端适配、CLI 与旧 tmux 边界
- [交互原型（prototype.html）](prototype.html) — 可直接拖拽分屏、实测独立跨行选字复制、关闭窗格 DOM 聚光灯与桌面/手机切换的可运行原型
- [技术设计（tech.html）](tech.html) — 后端单窗格直连协议、布局实时同步、前端 `SplitTree` 接入、WebGL 上下文预算与验证清单

关联前置架构：[三平台原生终端（20261120-native-pty）](../20261120-native-pty/README.md)
