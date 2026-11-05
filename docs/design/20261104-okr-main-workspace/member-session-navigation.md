# 长期成员直达原会话

关联 #693 / #658。运行态仍以 Main 为默认入口；用户选择某位成员后，“打开会话”应直接进入该成员原有的 Codex/Claude 对话，无需再打开一次任务详情。

## Product Design / User Stories

- 原任务保留真实 session/revision/run，直接进入原实例，不创建或恢复替代者。
- 遗留任务的项目字段为空时，允许使用宿主会话概览的注册 projectKey 佐证；不在浏览器根据目录或显示名猜项目。
- 任何归属冲突、过期执行轮次、重复会话、关闭或失活状态都回到当前真实任务。

## Technical Design

真实旧 CLI 续派目标为 session，Go 工作区回执的 projectId 为空；不能单靠回退 intent 补齐。前端复用已有 useSessionOverview，读取宿主基于持久 home 与项目台账生成的 projectKey。仅当 task.projectId 缺失、task.origin_conversation_id 等于本团队原 Main、同名活会话唯一、执行器和 projectKey 均匹配时允许直达。显式冲突永远拒绝；原生 nativeSession 不使用 CLI 概览作为补证。

GET 返回后继续核对成员/实例/task/revision/run/关闭状态，同时复核等待期间项目与 Main 未变。原 send、任务、成员、provider 和历史均不修改，没有新轮询或按成员查接口。该补证不改写 task 的执行目标归属，不将群聊归属冒充真实工作区绑定。

## Acceptance

浏览器真实项目先复现安全回退；新增桌面/手机行为回归在修复前失败，修复后通过。负例覆盖缺失/其他项目、其他Main、显式冲突、宿主冲突、native别名、重复/休眠会话及等待期间绑定变化，原有revision/run/关闭检查继续保留。专项、完整前端与发布证据在本轮PR补录。真实手机仍遵守用户不触手机边界，模拟不得算触控通过。
