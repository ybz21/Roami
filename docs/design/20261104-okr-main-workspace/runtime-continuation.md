# 持续目标指引与 Native 启动前拒绝

## Product Design

用户说持续运行时，原 Main 应发现并启用已有目标入口，再接续原成员；一次普通派发不等于持续目标已经保存。
同一目录的前一写入者未解除围栏时，新 Native 任务保留启动前拒绝与阻塞引用，不能把它说成已执行取数。

## User Stories

- Main 区分一次性任务与持续项目目标，已有有效目标直接接续，不自动复制成员或创建替代 Main。
- 成员未开始就遇到目录围栏时，Main 能看到真实原因和阻塞者，而不是只得到一个“结果未知”标签。
- 旧执行是否停止、效果是否已知仍独立核验，不能凭新任务未开始而解除旧围栏。

## Technical Design

真实原 Main 回合只调用 conversation_history、原任务续派和群聊回告，未调用新目标入口。
默认 Main 指引仍要求一次派发后结束，项目 main.md / swarm-execution 也未讲清持续目标入口。
补条件性的能力发现指引：只对用户明确要求的持续项目工作检查 status，引用当前真实用户目标启用；
短任务不自动转为持续运行，不用解析关键词或模型自造授权，也不把提示拼入用户原文。
核对原成员实际目录后再安排并发；不同 workspaceId 可能共享目录，不能把这类写任务当成独立并行工作。

Native HoldNative 在 claim 失败时复用 workspaceClaimResult，先持久保存再输出安全结构化结果。
Python hold_workspace 仅在完整的 workspace_claim / executionStarted=false / not_started 证明存在时
携带有界诊断，TaskDispatcher 保留它；没有完整证明的旧版未知回执及已开始后丢失控制继续保留未知。
这只证明新执行未进入 Native 工具，不证明前一 writer 停止或效果已知，不修改 writer.json、锁、busy 或旧结果。

## 验收

覆盖 Native 真实 Go 路径的持久结果/输出一致、原围栏保持、新执行无 started 标记、Python 传播、
无效/旧版回执不伪造证明及已开始后未知保护。完成门禁后 PR、合入、部署，再用原 Main / 原任务实际接续。
运行态不输出原始 stderr、账号或路径正文。当前源码修改不等于发布循环已跑通。
