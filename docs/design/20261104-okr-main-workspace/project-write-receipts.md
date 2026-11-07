# 项目写入回执（Go/API 第一段）

## 产品设计与用户故事

自动循环中 Main 可能在写入成功后丢失回执。恢复时应取得原观测、复盘或记忆追加的真实回执，不能因为工具调用变了或重新读取修订/CAS 就再做一次。本段只实现宿主的项目写入能力，不开放自动调度、内容冻结或外部发布。

普通无 operationKey 调用保持原行为。新的可选 operationKey 为项目内业务身份，同键同语义返回原回执，同键不同正文或操作类型拒绝。生产者必须绑定真实业务批次；任意新键本身不代表有发布或执行权限。模型端接线在后续 PR 实现。

## 技术设计

已注册 project-okr.db 显式 schema2→3，新增 project_operations，主键为 project_id/operation_key。保存操作类型、语义摘要、冻结意图、prepared/applied 状态和实际回执。意图身份与 applied 回执不可修改。不改变 confirmedSnapshot 文件格式，不搬迁旧观测/复盘，不是看板指标 SQLite 迁移。

- project-operation-receipts.go：校验稳定键与语义摘要，保存真实意图和回执。
- project-fact-receipts.go：预先分配 ReviewID/ObservationID；只以 current.json 所指的确认快照中完全相同的真实事实进行崩溃对账，JSONL 投影不是提交证明。
- memory-append-receipts.go：保留原字节、separator、旧/新 SHA，原子追加后从当前文件或已有 memory/history/<SHA>.md 对账，不能拿新 CAS 重复追加。不能证明原提交时保持冲突。
- project-files.go：提取既有锁内修改路径，避免嵌套取同一项目锁；安全路径/原文件所有权与原生布局继续使用既有实现。
- API：record/review/memory 接受可选 operationKey；memory 仅 append，可选键不能与 Connector batch 混用。Connector 已有批次身份和原请求摘要，继续原协议。新响应只在本次带实际 operationReceipt，不写入普通配置；projectFiles.operationReceiptsSupported 显式声明能力。

回执包含 key/kind/requestSha256，以及真实 observationId/reviewId 或 previousSha256/resultSha256 和 recordedAt；它只证明宿主项目写入，不证明指标真实性、平台已公开或任务验收通过。相同键重放在修订/CAS 检查前返回原回执；不同项目同键相互独立。

## 崩溃与迁移

持有既有项目锁，先提交 SQLite prepared 意图，再提交项目事实或记忆文件，最后保存 applied 回执。回执写入失败、进程重启和后续正常修改后仍恢复同一意图；未确认的新投影不能冒充成功。测试用实际 SQL trigger 注入回执更新失败，再重新打开存储对账。

隔离复制件已通过真实 Paths.Ensure + Go Open 从 schema2 升到3并 Get：49条观测、3份复盘可读，150个文件字节及旧表行保持，新增操作表为空，integrity/FK通过。它是旧代码候选的迁移专项，当前最终源码完整门禁仍待跑；未迁移线上库。

部署必须先保存完整真实库/项目文件备份并核对原 Main、成员、provider 与运行状态。schema3 后禁止回退到只识别2的 Go，也不能用旧库覆盖新的真实工作。准备兼容3且关闭新能力的恢复版本，或保持当前兼容3服务修复；Python schema26 不因这一段变化。当前生产不受私有候选影响。

## 验收与交付边界

专项覆盖重放/异文冲突、0值、跨修订回执、失败后重开、确认指针断点、后续记忆历史、跨项目、并发与 schema2 迁移。最终在本工作区跑 Go/API 完整门禁与正常提交门禁；不触发无关 Python/Skill 全套。真实 CLI/API 验收、截图与部署结果另记。

下一段接实际 coordination batch/lease 到写入身份、能力发现与小回执；之后接原批次恢复、结果桥接、事件/日槽生产者、真实审核冻结/发布通道。最终仍需原成员至少两轮真实平台发布、Connector 确认、看板更新、记忆复盘和下一轮任务。
