---
name: 取消期间的失败收尾与续跑
description: 执行报错后保存完整失败记录，再传播取消；保留原始错误、关机恢复及未知写入阻断，防止任务永久停止中。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开 `python.log` 和 `python.xml`。`input/controls.json`定义三类失败、收尾暂停位置和取消信号；`tools.json`列出22项检查及依赖。模拟执行器、真实Runtime/Scheduler/SQLite，不调用外部模型。
