# Agent 框架设计 · 2026-10-17

当前版本：[v6 设计报告](index.html) · [产品交互原型 v1](product.html) · [产品设计说明](product.md) · [整体技术设计 v1](technical/index.html)。这是设计提案，尚未实现运行时；报告内流程为交互模拟。

## 设计决策记录

| 版本 | 本轮确认的设计 |
|---|---|
| v1 | 调研 Pi、OpenClaw；Main / 子 Agent、自研工具循环、Memory、压缩、Fork、Browser / Computer Use。Claude Code / Codex 复用 Roami / ttmux CLI；记忆按任务、对话、日期组织。 |
| v2 | 用户指定 Python 实现内核、Go 对接用户；初步划分两层接口。 |
| v3 | 简化为 Python 完整服务，包括消息接口、流与 CLI 执行；Go 只复用现有统一鉴权并透明转发。 |
| v4 | Main 面向用户意图，去向包括直接处理、已有项目、已有散会话、新散会话和新项目；projectId 可空。 |
| v5 | 用户强调快问快答为第一目标；普通问答直达模型，任务快速入队，资源准备与执行后台化。按用户要求迁入日期目录。 |
| v6 | 增加统一 ReplyService 与拟新增 agent report / reply CLI；原生 Main 直接流式输出，外部执行器通过 CLI 回报或获准代答，回复绑定原始主对话。 |

迁移前版本保留为 [v4 快照](revisions/v4.html)，快问快答方案保留为 [v5 快照](revisions/v5.html)。v1–v3 的决策据会话记录整理，未伪造当时文件快照；本目录从 v4 开始保留实际快照。

## 产品设计迭代

- 产品 v1：主对话优先；桌面三栏、手机四项底部导航；任务去向选择、已有散会话续派、新项目、任务回报、取消和记忆浏览。交互与验收范围见产品设计说明。

## 实现边界

- Python：消息 API、SSE、Main / Worker、工具、记忆、压缩、调度、CLI 执行器及运行时库。
- Go：复用 Roami 登录鉴权，统一入口，透明转发消息和流；不维护另一份 Agent 业务状态。
- 现有 CLI：启动、续派和恢复 Claude Code / Codex；结构化回执缺口见报告。
- 目录来源：`docs/design/agent-framework/index.html`，本轮移入此目录。

## 调研与验证

官方资料与本地源码依据均在报告末尾；本地源码核对基线为 `6907b15`，不是声称后续每轮都重新拉取主干。

报告交互验证覆盖 6 个宽度、6 个架构模块、5 种记忆视图和 8 个流程场景。此前 Android 真机锁屏，未完成真实触控验收；窄屏浏览器模拟已检查。延迟数值均为待实测目标，不是已获得的性能结果。

## 技术设计迭代

- 技术 v1：独立总览与 10 个子 HTML，覆盖对话持久化、记忆写入、范围检索、Prompt / 应用缓存、模型与工具循环、任务 / CLI 回报、Go 流转发、恢复与验收。
- 附完整候选 `technical/schema.sql`、可重跑的 `technical/validate-schema.py` 和 `technical/validation.md`。建表规范经过临时库验证，尚未作为生产迁移运行。
- 官方资料与项目设计选择的边界见 [技术依据](technical/sources.md)。
