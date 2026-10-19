# Agent 技术设计 v2

入口：[总览](index.html)。本目录保留技术 v2 提案及后续模块；早期“尚未实现”描述是历史基线，当前状态以对应模块和日期验证记录为准。

- [候选 DDL](schema.sql) 是完整建表规范，不是生产迁移。
- [验证记录](validation.md) 区分已运行的结构与原型检查、待实施的运行时与性能验收。
- 设计基于产品报告 v7；Python 完整服务，Go 统一鉴权并透明转发，CLI 复用统一 roami session / chrome / project。
- 子页面中的外部事实链接到官方文档；字段、目录与时延数字是本项目设计选择。
- HTML / CSS / JS 使用相对引用，可整目录离线阅读；公开预览通过 Roami file/serve。

- [统一 CLI 对齐清单](cli-alignment.md)：以 a27f13a / CLI v4 为依据，区分已有能力与待实施桥接。

- [主动联系与未读消息](11-proactive-messaging.html)：触发、统一回复、右上角红圈、已读水位、免打扰与 App 推送边界。

- [基础四工具与 tool_list](15-tool-discovery.html)：2026-10-18 用户确认保留 read / bash / edit / write，增加 Skill / CLI 搜索；另有 delegate / ask_user，Main 总计 7 个。包含自动记忆与召回修订。

- [执行器边界与路由](../../20261019-执行器边界与路由/index.html)：2026-10-19 补充 Main / native / 专业执行器职责、可信目标、偏好与能力约束、失败 / Fork 边界；v3 明确开放任务范围与复杂度解释，专业智能体承接各类复杂工作，调研、原型、PPT、剪辑等仅作举例，不按领域硬编码，附源码审查与 48 条待实施验收预期。
