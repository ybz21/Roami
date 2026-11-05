# 未派发的 Roami 成员会话

关联 #656 / #658，接续长期成员账本。此阶段仅处理 Roami 原生成员；Codex/Claude 的无任务常驻启动与统一 Web 对话入口仍需后续实现。源码未部署，不改变现有项目实例。

## 产品设计与用户故事

登记原生成员后，它已有独立、持久的会话与职责上下文，但没有业务任务、执行轮次或完成状态。Main 第一次给它安排工作时使用这一会话；后面继续原 task 的 revision，保留个人上下文。

用户能从成员详情读取真实会话身份；空闲与任务验收分开。成员不会混入首页对话，不会成为另一个 Main。会话被删除或显式关闭后保留原绑定，不自动创建替代者。旧未知回执仍需核对，不能因为有成员会话就重试或判成功。

## 技术设计

Schema21 增加 `swarm_member_instances`，将 member、owner、conversation、branch 与可空 task 分开。新原生成员在同一登记事务中建立会话和职责说明，不排队 Main turn、不运行模型、不伪造成功任务；模型角色不通过会话展示名推断。

首轮任务创建采用内部 `memberInstanceId`：校验同 owner、原 Swarm Main、当前 work key、未绑定实例及固定 branch，再复用 conversation/branch。task、native session、instance/task 绑定、work/task 绑定与首轮请求全部在同一事务提交。后续 task_revision 保留该上下文，当前验收和每轮执行记录仍由 Tasks 负责。

旧成员只按当前 work/task 到实际 native_sessions 的明确绑定回填；不裁名字后缀、不改变 task、run、native session 或未知结果。未绑定 work 若已有孤儿 launch，则要求核对，不新建对话掩盖它。没有充分绑定的成员不会凭目录或最近会话补造身份。

首页、项目 Main 和 Swarm Main 的选择均排除这些成员。数据库拒绝把成员会话绑定为 Main、移动成员实例身份或把已绑定实例换到新 task。普通 chat 入口拒绝将成员当 Main；模型入口再次核验真实 task/run/revision/branch，防止低层 intake 绕过。此阶段未派发成员只有读取入口，独立闲聊/接任务的入口继续单独接续。

成员快照以一次查询附带实例摘要，不新增逐成员轮询。CLI `members --json` 保留原生实例信息，`member inspect` 提供准确 conversation ID；旧协议0的工作项 JSON 仍不变。

| 模块 | 职责 |
| --- | --- |
| member_instances.py、0021_member_instances.sql | 原生会话身份、迁移、不可变绑定与摘要 |
| swarm_members.py、swarm_plans.py | 登记实例及首次真实派工 |
| dispatch/tasks.py | 复用预留会话，原子绑定首轮任务 |
| conversation_identity/project_main/transcript/service | 正确展示与 Main/成员隔离 |
| prompt_builder.py | 模型入口的 task/run/revision/branch 检查 |
| storage/backup-set 与 CLI | schema21备份兼容、真实会话详情 |

## 验收

83项原生实例、长期成员、Swarm、首页/项目身份专项通过；Go CLI与存储专项通过。涵盖未派发时无业务任务/模型 turn，首次任务及三轮复用同一 conversation/branch，成员会话不能成为 Main，首页恢复不选择成员，删除空闲成员不产生替代者，以及旧角色/未知 attempt 与 native_session 原样保留。

旧库夹具按历史表结构建立记录后再升级，不使用新 Main 查询去操作尚无实例表的旧版本数据库。Go 备份接受1..21，拒绝未来22。

组合恢复实现后，完整门禁完成：Python3463 passed/48 skipped，Go全量、Ruff检查与格式、前端typecheck/i18n/hover/生产构建和仓库审计均通过。门禁基于3c50d462；#669合入e0fda2ae后重新基于主线的608d1623与其完整文件树一致（e8991de91b7967c01c8ee27144457ed850a6fa29），沿用相同源码的门禁，不重复跑Python全套。此前正常commit quick为原基线Python3452 passed/48 skipped。

真实 Go CLI → 私有 Python API 联验通过：登记时无业务任务或模型turn，读取准确成员身份；首次派工复用预留conversation/branch；连续三轮保留同member/instance/task/conversation/branch，分别产生文件并经过报告、独立验证、显式夹具用户验收。额外只读SQLite核对一个实例/一个任务及三轮记录，隐式research-r2被HTTP409拒绝。该夹具注入测试模型，不是线上宣传执行。证据 `/tmp/okr-member-instances/{cli-proof.log,cli-proof.json,full.log,merge-integration.json,acceptance.html}`。自建测试实例已按隔离入口回收，数据库和记录保留。

没有 Web UI 修改、手机操作、线上部署、模型路由/环境/费用/账目或 busy 变更。CLI输出、协议字段和Agent职责文本按i18n标准豁免。
