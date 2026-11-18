# 第一期：近期原文、工作简报与历史检索

本分支实现 Home 后端链路；不部署、不改当前节点的配置和原 Main 身份。

## 产品行为与用户故事

- 用户继续跨天工作时，简报保留有原话来源的未决要求；未完成任务额外带上完整原始要求及真实 taskId / revision，不受最近三项任务的限制。
- 用户问无关新问题时，旧一次性格式要求和执行日志退出常驻原文；需要旧决定时，由现有 `conversation_history` 工具检索关键词、时间范围或日归档，再按消息 ID 精确读取。
- 原文、工具轮和任务记录不删除，不创建替代会话。没有完成来源交接或生成失败时继续保留必要原文，不按日期直接丢弃。

默认近期目标为 48 小时、最多 20 个已完成回合，正在进行的完整回合保留。后台于空闲 10 分钟时整理，02:10 后补齐完整自然日，均使用已有 `[memory].timezone`。默认时区仍是 UTC；没有把节点时区静默改成北京时间。空闲时产生的当天归档明确属于来源批次，不宣称整天已覆盖。

模型生成的 `constraint` / `open_work` 必须引用真实用户原话；模型漏掉上一版约束不会自动使其消失。替代记录需要更新用户来源中的精确引文，任务约束展示实时任务作用域与状态。历史引用按当前问题筛选，中文单字重合不足以触发召回。结构校验不等同于语义准确率证明。

## 技术设计与模块边界

| 代码 | 职责 |
| --- | --- |
| `agent-runtime/src/roami_agent/context/retention_policy.py` | 完整回合边界、近期窗口、有界增量批次及包含位置/时间的来源指纹 |
| `context/working_brief.py` | 用户原话校验、约束替代、作用域和相关引用筛选，以及未完成任务原始要求 |
| `context/maintenance.py` | 持久作业、空闲/自然日调度、重启恢复、退避、保存路由调用和原子激活 |
| `context/projection.py`、`context/main_history.py`、`context/prompt_builder.py` | 来源验证后切换简报投影，保留近期/当前回合，装配真实任务与最终输入估算 |
| `retrieval/conversation_search.py` | 可重建 SQLite FTS 原文索引、修改队列、权限/分支/时间筛选，以及返回前再次回源校验 |
| `conversation/history_read.py`、`tools/main_catalog.py` | 扩展原有历史工具；保留分页和精确消息分块读取，不恢复整份历史协议 |
| `memory/period_summaries.py` | 读取日归档批次，逐个核对来源、分支血缘、版本、遗忘和删除状态 |
| `dispatch/scheduler.py`、`app.py` | 低优先级后台槽位与运行时装配；后台整理不占 Main 槽位、不锁住交互分支 |
| `storage/context_admission.py`、`observability/prompt_manifests.py` | 记录简报身份与任务依据；任务 revision / state 变化后禁止使用旧依据继续操作 |
| `agent-runtime/migrations/0029_context_lifecycle.sql` | 索引待办、FTS 文档、`context_briefs` 和独立的语义 `period_summaries` |
| `internal/storage/backup-set.go` | 同步 Go 备份恢复对 Python schema 29 的兼容上限 |

表中的短路径相对 `agent-runtime/src/roami_agent/`。没有把日活动计数表当成语义归档，也没有引入新的配额控制。

每次整理固定已完成来源水位，最多处理 20 个完整回合；模型输入按实际容量继续缩小批次。容量未知时仍可调度有界批次，不捏造窗口。长助手/工具日志只向摘要模型提供注明截断的片段，完整原文继续进入搜索索引。超出单批输入的用户原文不静默截断：保留原文并记录待恢复原因。

索引候选不是读取权限：返回前核对原始正文指纹、所有者、该请求真实分支及 fork 截止、当前回合边界、遗漏记录和遗忘指纹。单条搜索结果从匹配位置附近开始分块，消息 ID 与 offset 可以继续读取精确 JSON；原有 64 KB 返回上限保留。索引未补齐明确返回 `coverage.complete=false`。

简报激活时再次核对 branchEpoch、memoryEpoch、完整来源身份及作业运行状态；日归档与简报在同一事务提交。失效或失败不会半激活，也不会覆盖上一个有效版本。无新增来源不调用模型，后续补齐通过持久水位推进。原始历史保留，旧容量压缩仍可用。

## 配置、迁移与后续阶段

新增的四项 `[runtime]` 配置及边界校验见 [runtime README](../../../agent-runtime/README.md#memory-lifecycle)。关闭自动整理后不继续生成简报，原文搜索仍可使用。TOML 修改需要重启，网页配置和完整状态展示留在第三期。

schema 29 事务迁移会为现有已完成原文建立待索引记录；监督器有界补齐，不一次把历史交给模型。现有压缩快照沿用原格式与校验，没有改写旧会话、任务、模型路由或网关准入。

周／月／年归档、父子依赖、迟到结果修正和专门的来源浏览/配置界面不属于本期实现。现有上下文页面没有新增界面；API 和执行记录保留简报身份。性能证据限于同口径输入估算，不据此声称 CPU、内存、模型回答质量或总费用下降。
