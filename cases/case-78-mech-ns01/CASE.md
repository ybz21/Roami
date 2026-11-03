---
name: Native启动取消与任务续办
description: 在真实SQLite启动事务提交前后定点取消，验证准备和运行状态均能释放Native回合并应用用户续办，保留启动错误与停机中断，并覆盖停止收尾期间的重复取消。
---

`input/scenarios.json`与实际测试夹具逐字节一致。使用真实Runtime、SQLite与异步取消，执行者未启动；CLI检查使用本地HTTP模型替身和隔离的Go网关，不调用外部模型。

`input/cancellation-settlement.json`补充18项重复取消检查，覆盖续跑、停止、关机及未知写入；取消收尾必须完成后才退出。
