# 原会话续派的启动前诊断

## Product Design

同一 OKR 的原成员复用其会话时，目录可能正被另一成员占用。任务要保留本次尚未开始的事实、
拒绝原因及可用的阻塞者引用，让 Main 判断应等待还是对账。新执行未开始不表示此前 writer
已停止或效果已知；原任务、原会话与围栏继续保留。

## User Stories

- 原会话续派被正在执行的 writer 拒绝，看到 WORKSPACE_BUSY 和 not_started，不重发提示词。
- 此前 writer 的结果未知，看到原因及真实阻塞引用，保留原围栏并先对账。
- 重读同一请求返回已保存的拒绝结果，不新建实例或业务键。

## Technical Design

`Service.continueSession` 在 claimWorkspace 拒绝分支此前自行构造了简化 Result，只保存摘要和
exitCode。真实 Go status 与 Python 任务结果均因此缺少 executionStarted、exitCodeSource、
errorCode 和 failure。普通执行与 Native 已有统一的 workspaceClaimResult，此处分支复用它。

不改变身份恢复、会话空闲检查、目录申请、writer 生命周期或权限。Result 不补 inputStopped /
outcomeKnown，避免把本次未开始扩大成旧执行已确认停止。Python CodingExecutor.result 已保留
宿主 result 字段，无需新增错误字符串推断或放宽旧数据。

## 验收

新增原会话真实 Service.Launch/Status 回归，分别持有活跃目录锁、保留未知旧 writer；检查结构化
结果、原 writer.json 和会话 lifecycle 字节不变、没有提交提示词、同请求重读结果一致。

隔离草稿先验证旧实现会在两种场景丢失诊断，修复后两场景通过。当前主线工作区另跑完整门禁和
正常提交钩子；以最终源码与日志为准。关联 #785，整个自动审核/发布/取数目标不随本小修复关闭。
