# 任务看板

看板展示当前受管任务状态，不允许拖卡片绕过验收。Main 用 `swarm_plan` 提交 member、executor、title、goal、acceptance 和 dependencies；指定 revision 的上游验证成功后才派发下游。最终整合成员设置 integration=true。

查看使用 `swarm_status` 或 `roami swarm board <sw-id>`。成员自称完成进入回报/验收流程，不能手动 done；返工通过 task_steer 继续原任务。上游版本失效先确认停止，再通过 swarm_dependencies 重绑依赖。

UI 分为待办、进行、受阻、待审和完成；需要输入、失败和未知状态必须保留真实原因。
