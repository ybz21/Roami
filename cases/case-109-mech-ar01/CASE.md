---
name: 精简历史中的回复送达事实
description: 区分已收到回复的旧问题、未回答提问和后台任务状态，保留按需读取原文及遗忘、删除和用户隔离边界。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开 `python.log` 和 `python.xml`。`input/controls.json`是公开的交错对话，`tools.json`列出检查与依赖。使用模拟提供方、真实Runtime和SQLite，不调用节点模型。
