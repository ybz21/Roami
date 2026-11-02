# Roami 文档

> **随时随地，掌控众多 Agent。** — 品牌名 **Roami**，统一命令入口 `roami`。

| 目录 | 内容 |
|------|------|
| [features.md](./features.md) ｜ [features.zh-CN.md](./features.zh-CN.md) | **完整功能列表** — 按能力分类 |
| [Roadmap](../ROADMAP.md) ｜ [中文路线图](../ROADMAP.zh-CN.md) | **下一阶段** — RSI 自进化、接入 SuperWork 构建数字分身、OKR 自动执行 |
| [deploy/mobile.md](./deploy/mobile.md) | **手机与 Android App** — 安装、签名、通知与构建 |
| [install/](./install/) | **安装与部署** — CLI 一键/源码安装、Web 控制台启动、`.env` 配置、远程访问、故障排查 |
| [design/](./design/) | **历史设计文档** — swarm / plugin / web / cluster；新设计按根 AGENTS.md 维护 |

## design/ 速览

设计文档按主题分目录，每个目录一组：

**[swarm/](./design/swarm/)** — 蜂群编排
- [蜂群编排设计](./design/swarm/蜂群编排设计.md) — swarm / member / master / 依赖门控
- [蜂群广场与看板设计](./design/swarm/蜂群广场与看板设计.md) — Plaza（消息流）+ Board（看板）
- [蜂群广场监听循环设计](./design/swarm/蜂群广场监听循环设计.md) — master/worker 持续监听 human 指令与广场消息
- [蜂群 Web 接入设计](./design/swarm/蜂群%20Web%20接入设计.md) — 蜂群在 Web 端的映射
- [蜂群成员启动与提示词模板设计](./design/swarm/蜂群成员启动与提示词模板设计.md) — claude/codex 引擎 · master/worker 角色 · 提示词模板（Go text/template）
- [蜂群成员角色模型设计](./design/swarm/蜂群成员角色模型设计.md) — 细分角色(产品/工程/测试…) + 职责 · 全链路

**[plugin/](./design/plugin/)** — 插件机制
- [插件机制设计](./design/plugin/README.md) — 调研 / 产品 / 架构(plugind) / manifest / 平台 API / 安全 / 路线图 / 开发指南
- [智能评审插件设计](./design/plugin/智能评审插件设计.md) — Codex + Claude 互审、finding、裁决与 swarm 质量闭环
- [飞书常驻管家设计](./design/plugin/10-feishu-concierge.md) — IM 桥 + concierge 委派

**[web/](./design/web/)** — Web 控制台完整设计（总览 / 后端 / 认证 / 前端 / 逐页面 / 路线图）

**[cluster/](./design/cluster/)** — 多机管理（一个入口管所有开发机）：
[ui.html](./design/cluster/ui.html) 视觉 ｜ [settings.html](./design/cluster/settings.html) 设置页与初次安装 ｜
[architecture.html](./design/cluster/architecture.html) 技术架构 ｜
[mockups/index.html](./design/cluster/mockups/index.html) 可点原型（多机只加的那三样）

## 相关

- [Roami UI 设计规范](./development/ui-design-system.md) — 配色、布局、尺寸、手机与桌面规则（强制）；[手机 Material 细则](./development/mobile-material-ui.md)
- 根 [README](../README.md) ｜ [README.zh-CN](../README.zh-CN.md)
- [会话 CLI](./development/session-cli.md) — `roami session`
- [统一命令入口](../cmd/roami/cli.go) — `roami`、`roami chrome`、`roami agent` 等
- Web 后端说明 [`backend/README.md`](../backend/README.md)
