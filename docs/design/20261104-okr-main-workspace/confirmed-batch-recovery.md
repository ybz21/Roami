# 已确认批次的读取与恢复

关联 #825、#761。现场批次 `3ff70117a10175761a5373487063d6be` 已在 revision 48 确认；Main 在 revision 51 改 note 重试得到正确冲突，却误报“作废不入库”。原 77 条观测仍保留。完整上下文 164752 字节被外置，预览从旧回执开始，最新回执不在预览中。

## Product Design

Main 直接按批次 ID 读取紧凑确认回执，区分已经确认、未找到与当前请求冲突。新发布扩大集合不撤销旧集合在原采样时刻的历史事实。保持旧数据、原 Main 与原成员；不放松同键不可变约束。

## User Stories

- 记账后回执丢失，再读同一 ID 可确定已确认，不因当前 revision 推进而重发。
- 同键改 note 被拒绝时，明确读取原确认回执；不能称旧记录作废。
- 跨项目 Main 和成员不能借批次 ID 读取另一项目的事实。

## Technical Design

增加只读 `swarm_connector_batch`，CLI 为 `roami swarm connector batch --input JSON`，参数仅 swarmId/batchId。复用当前 Main、swarm/project 绑定及现有 project show，不接受调用方自选项目或路径。普通 Main 与协调批次共用入口；协调目录将其归入 SWARM_READS。

`tools/connector_batch_receipts.py` 从确认工作区按 ID 精确选择，返回 projectId、当前 revision、confirmed/not_found，以及原批次 revision、时间、来源、请求摘要和 observationIds。省去完整项目与大段归档路径；完整资料仍通过 project context 的留存 artifact 读取。重复/无效回执视为协议错误，不拼造确认状态。

record 返回 OKR_CONFLICT 后，仅对合法批次 ID 只读查当前确认结果；已有确认回执时返回 `CONNECTOR_BATCH_ALREADY_CONFIRMED_REQUEST_CONFLICT`，保留失败状态，不改请求、不自动重试。查询失败时保留原冲突。新错误及工具描述指向批次读取入口。

## Acceptance

隔离覆盖普通与协调 Main 实际 CLI、发现、跨项目/成员拒绝、未找到、重复/损坏回执、当前 revision 推进后读取原回执；改 note 仍失败，旧观测与批次不变。真实现场确认结果读取以及下一轮新批次入库另留验收证据，不能以新增工具已注册宣称线上完成。

首轮 9 项专项与扩展协调/写入/上下文回归共 69 项通过；普通 Main 和协调 Main 均经实际 Foundation CLI 读取。格式化函数也只读核验真实 revision 53 工作区，正确返回旧六稿批次 confirmed / 原 revision 48，不输出完整观测或大段归档路径。真实后续九稿已由现有 Main 入库，旧 77 条保留；新工具尚未上线，不能据此认定 #825 生产验收完成。
