# 群聊协作

Main 和成员使用 `swarm_post` 记录进展、接口约定与阻塞。`swarm_status` 返回真实群聊、任务与依赖快照。用户在群聊发送给 Main 的消息进入同一 Main 对话；指定成员的消息沿原任务修订。

专业执行器使用任务提示中的宿主绑定，通过 `roami swarm post <sw-id> --file message.json` 回传。请求包含 commandKey、text、taskId、runId、taskRevision，作者由宿主校验，不能自行指定其他成员。

普通讨论不改变任务状态。完成报告走任务 report 和独立验收，重要任务结果经 completion turn 回到原 Main。
