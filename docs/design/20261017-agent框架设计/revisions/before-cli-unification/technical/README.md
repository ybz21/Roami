# Agent 技术设计 v1

入口：[总览](index.html)。10 个子模块分别描述对话保存、记忆存储、召回、上下文与缓存、运行时、任务 / CLI、传输、运维验收、工具网关与 Browser / Computer Use。

- [候选 DDL](schema.sql) 是完整建表规范，不是生产迁移。
- [验证记录](validation.md) 区分已运行的结构与原型检查、待实施的运行时与性能验收。
- 设计基于产品报告 v6；Python 完整服务，Go 统一鉴权并透明转发，CLI 继续复用 Roami / ttmux。
- 子页面中的外部事实链接到官方文档；字段、目录与时延数字是本项目设计选择。
- HTML / CSS / JS 使用相对引用，可整目录离线阅读；公开预览通过 Roami file/serve。
