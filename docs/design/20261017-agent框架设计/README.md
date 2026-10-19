# Agent 框架设计 · 2026-10-17

当前版本：[v7 设计报告](index.html) · [产品交互原型 v4](product.html) · [产品设计说明](product.md) · [整体技术设计 v2](technical/index.html)。本文保留 2026-10-17 的提案基线，报告内流程为交互模拟；后续已有部分运行时实现，不能把旧文中的“待实现”当作当前全量状态。新增模块以日期补充和各自验证记录为准。

## 设计决策记录

| 版本 | 本轮确认的设计 |
|---|---|
| v1 | 调研 Pi、OpenClaw；Main / 子 Agent、自研工具循环、Memory、压缩、Fork、Browser / Computer Use。Claude Code / Codex 复用 Roami / ttmux CLI；记忆按任务、对话、日期组织。 |
| v2 | 用户指定 Python 实现内核、Go 对接用户；初步划分两层接口。 |
| v3 | 简化为 Python 完整服务，包括消息接口、流与 CLI 执行；Go 只复用现有统一鉴权并透明转发。 |
| v4 | Main 面向用户意图，去向包括直接处理、已有项目、已有散会话、新散会话和新项目；projectId 可空。 |
| v5 | 用户强调快问快答为第一目标；普通问答直达模型，任务快速入队，资源准备与执行后台化。按用户要求迁入日期目录。 |
| v7 | 对齐统一 CLI v4 / main a27f13a：标准命令树、共享应用服务、项目 API 单写、固定 OID worktree、catalog / 路径 / 维护锁与备份边界。 |
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

官方资料与本地源码依据均在报告末尾。初轮基线 `6907b15`；CLI 对齐轮重新核对 `a27f13a`（#328）与 [统一 CLI v4](../20261017-CLI统一设计/index.html)。

报告交互验证覆盖 6 个宽度、6 个架构模块、5 种记忆视图和 8 个流程场景。此前 Android 真机锁屏，未完成真实触控验收；窄屏浏览器模拟已检查。延迟数值均为待实测目标，不是已获得的性能结果。

## 技术设计迭代

- 技术 v1：独立总览与 10 个子 HTML，覆盖对话持久化、记忆写入、范围检索、Prompt / 应用缓存、模型与工具循环、任务 / CLI 回报、Go 流转发、恢复与验收。
- 附完整候选 `technical/schema.sql`、可重跑的 `technical/validate-schema.py` 和 `technical/validation.md`。建表规范经过临时库验证，尚未作为生产迁移运行。
- 官方资料与项目设计选择的边界见 [技术依据](technical/sources.md)。

- 技术 v2：与统一 CLI / Go 共享业务服务和统一存储规范对齐，详情见 [对齐清单](technical/cli-alignment.md)。CLI 对齐前的完整实际快照保存在 [revisions/before-cli-unification/](revisions/before-cli-unification/README.md)，已有 v4 / v5 快照不变。

- 产品 v2：加入 `/compact [关注项]` 命令提示、上下文入口、排队 / 运行 / 完成 / 取消 / 无需压缩反馈与摘要查看。技术设计补齐控制接口、分支串行化与持久化复用；仍是本地交互模拟。

- 同轮增加 `/help`、`/status`、`/tasks`、`/memory`、`/stop`，统一命令提示与补全；停止回复、取消任务、取消压缩分属独立操作。首批不引入清空历史或重置全部状态的命令。

- 产品 v3：保留工作台导航，补齐桌面项目 / 工作会话树、历史主对话切换、新建主对话、项目快捷建任务和执行器选择；任务结果绑定原始主对话，切换历史不改变回报位置。

- 产品 v4：新增大总管主动联系、右上角未读数字圈、历史红点与通知消息定位；新增技术子模块 11。Python 通知持久化已开始实现，系统推送适配尚未接通。

## 2026-10-18 已确认补充

用户确认上下文使用到容量 75% 时自动压缩。已同步 [上下文与 Cache](technical/04-context-cache.html)，变更前版本保存在 [修订快照](revisions/before-75-percent/technical/04-context-cache.html)。仅这一项获得实施确认；[Pi 机制审计](../20261018-Agent机制对照/README.md) 的其他补齐建议仍待确认。

## 2026-10-18 容量口径修订

用户明确取消默认容量及固定输入 cap：按 Main / Worker 当前模型实际上下文窗口的 75% 压缩。已同步 [上下文与 Cache](technical/04-context-cache.html)，上版留在 [修订快照](revisions/before-model-capacity/technical/04-context-cache.html)。模型元数据缺失时明确未知，可在设置页填写实际规格，不能默认套用 24K。

## 2026-10-18 聊天图片预处理

用户确认按 Pi 做图片预处理。已同步 [上下文与 Cache](technical/04-context-cache.html) 的图片专项；上版保存在 [修订快照](revisions/before-image-preprocessing/technical/04-context-cache.html)。浏览器上传前优化，Python 按模型限制兜底，合规原格式保留、透明白底 JPEG、EXIF 与编码体积控制，重试复用同一份文件。此项不代表其他工具图片协议已统一。

## 2026-10-18 唯一 Main 与 CLI 派活

用户确认只展示一个长期 Main，其他执行器会话作为后台任务。补充 [派活机制与唯一会话](technical/12-roami-dispatch.html)：内置技能、完整项目会话查询、已有会话直接投递、选择题、后台新建及真实状态回报。旧记录保留，不自动拼接上下文。

## 2026-10-18 专业智能体管理提案

按本会话要求新增 [专业智能体管理](technical/14-professional-agents.html)：卡片原型、已有与待补能力、主对话使用路径、用量 / 额度口径、适配器边界和分步验收。替换“可执行文件”的产品命名；新增目录 / 用量服务仍为待评审设计，不表示已经实现。

## 2026-10-19 执行器边界与路由

新增 [Main / native / 专业智能体路由设计](../20261019-执行器边界与路由/index.html) 及 [源码审查记录](../20261019-执行器边界与路由/review.md)。v3 按用户补充区分短问答、简单工具工作与各类复杂任务（如调研、原型、PPT、剪辑等，按实际执行负担判断），并区分已有会话投递与受管任务续接；补齐选择顺序、上下文、失败切换、产品呈现和 48 条待实施验收场景。统一路由策略已在工作区实现，尚未部署；实际测试与限制见 [实施记录](../20261019-执行器边界与路由/implementation.md)；已有回报协议见 [原会话派活回报](../20261019-派活回报/README.md)。
