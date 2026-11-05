# 原 provider 对话的可信恢复

关联 #656 / #658，接续 [长期成员与轮次](long-lived-members.md)。本文件描述下一阶段源码，尚未部署，也不表示现有旧会话已获得恢复证明。

## 产品设计与用户故事

职责成员、任务和对话上下文保持不变。终端消失后，继续用户明确追加的下一轮工作；只有物理终端需要重建。完整保留旧执行与失败回执，并标明新终端来自哪个原会话。

- 正常空闲实例继续接收原任务的新 revision，不创建新实例。
- 终端丢失但上轮结果已知、旧进程已停止时，接回原 Codex/Claude 对话、原工作区与原配置目录。
- 恢复前置检查失败而且证明尚未接收输入时，保留原 provider 绑定，允许用户显式续派后再次检查；结果不明时禁止重放。
- 用户显式关闭的实例不恢复。首页 Main、OKR Main 与其他任务的原生对话不能成为替代来源。
- 启动、投递与 provider 完成不等于任务验收；继续原 Tasks 的独立验证和用户验收。

## 技术设计

Python 不控制终端。`CodingExecutor` 首先走现有原 session 的继续入口；只有严格观察到 `SESSION_TARGET_NOT_FOUND`，才把当前任务持有的原 attempt launch key 和 provider ID 交给 Go 恢复。

`continuation.providerRunId` 是已确认原生绑定的显式引用。它仅指向同 owner、同 task 的 CLI attempt，保留 node/session/provider 关系。跨越失败尝试时，每一项都必须证明 executionStarted=false、outcomeKnown=true、inputStopped=true，不能扫描最近活跃会话或跳过 unknown 写入。

Go 验证原 spec、receipt、生命周期与结果：executor/provider/session 精确匹配；CompletedKey 和 promptHash 指向原轮次；没有待完成工具或较新的输入；结果及停止证明明确；原物理会话确实消失；没有显式关闭记录。新的 binding 保存宿主 boot/machine/进程、cgroup 与 mount namespace 证明，目录及 provider 配置目录的文件系统身份。缺少证明的旧记录不会反向补造。

原 pane 的已保存 cgroup 独立于 root PID 观察。检查实际 cgroup v2 文件系统、专用 scope、完整进程列表和原 PID start token；同 scope 的孤儿写入或原进程仍存活时不恢复。观察失败不是停止证明。

原 provider 历史必须属于准确的 ID 和目录，且最后完整轮次匹配。恢复保留显式 model/permission 和原配置目录，不切换模型路由或账户。原配置目录仅恢复到执行器自身的专用 Run 进程，不修改服务或用户全局环境。

使用原生命周期锁、恢复占用记录、launch 幂等记录、工作区 writer 围栏和 Run 的一次性 started 记录。占用一旦结果不明便不能再次启动；只有完整证明前一恢复未接收输入、其终端已消失时才允许下一次显式请求占用，并保留前次占用和所有 journal。新终端执行标准 `codex resume <准确ID> <文件请求>` 或 `claude --resume <准确ID> <文件请求>`；初次真实输入回调前不把预期 provider 当成已确认 binding，回调不得接纳另一个 UUID。

| 模块 | 职责 |
| --- | --- |
| storage/task_provider.py、task_revisions.py | 明确保存和校验原 provider attempt 引用；保留失败与验收 |
| executors/roami_cli.py | 仅在原终端确实缺失时请求受管恢复 |
| agentexecution/provider-recovery.go、session-host.go | 宿主、来源、工作区、停止证明与占用检查 |
| agentexecution/persistent-session.go、session-lifecycle.go | 原生启动、确认输入、恢复身份围栏及完成检查 |
| memguard/RecordedScopeProcesses | root PID 消失后读取原专用 scope |
| cli/spawn/agent.go | 准确 UUID 及文件请求的安全 resume 命令 |

## 验收记录

源码阶段已验证两种假 provider 的真实私有 tmux/Go CLI/Python 联验：物理终端变化、provider UUID 与工作区保持、重放不重复输入。相关 Go 身份、进程、占用、原始请求回归和57项 Python执行/续派专项已通过。

最终扩展隔离场景已通过：四个 task revision 对应三次真实假 provider 输入，中间一轮为明确未启动的临时恢复失败；失败不丢原上下文，随后继续同一恢复后的终端。原物理会话的历史仍为 dead，新会话有准确 restored_from。真实 Tasks 报告、验证和显式夹具用户验收分别执行；同一 launch 重放不重复输入。最终相关 Go 专项通过（含两种真实私有 tmux/CLI/Python 场景及旧常驻实例回归），Python57项专项通过。完整 quick/full 已通过：Python3457 passed/48 skipped、Go全量及前端构建/审计。原代码提交7b79547d，主线同步后01eaeef2；同步仅包含其他已合入的Go/前端侧栏改动，agent-runtime目录逐文件相同。按真实7b..01e新增差异另跑full（Python未变化故跳过）和前端全量1376项，均通过。最终私有CLI场景 `/tmp/okr-provider-recovery/scenario-final.log` 在01e源码重建二进制上通过；数据库独立复核四轮状态、同provider、同task、恢复后同终端，报告 `/tmp/okr-provider-recovery/acceptance.html`。CLI与Agent职责文本属于i18n标准豁免，本轮未修改Web UI。

证据目录 `/tmp/okr-provider-recovery/`。所有 provider 均为本仓测试夹具，未调用真实模型、手机或线上项目，没有部署、重启服务、修改路由、费用、账目和 busy。

仍待后续：无任务职责的原生常驻实例、Web 成员预览/直接对话入口及旧重复职责显式 CAS 迁移。此恢复协议不替代这些需求，也不迁移线上 unknown 或已关闭实例。
