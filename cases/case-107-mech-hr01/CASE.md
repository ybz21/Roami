---
name: 精简历史保留可信派活回执
description: 保留历史请求对应的任务接收与续跑事实，覆盖来源隔离、未知和拒绝状态、部分请求、遗忘删除以及完整历史恢复。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开 `python.log` 和 `python.xml`。输入为 `input/controls.json`，工具、18项选择与依赖见 `tools.json`。使用模拟提供方和真实Runtime/SQLite，不读取节点凭据，不调用外部模型，不执行任务交付。
