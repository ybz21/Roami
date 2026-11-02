---
name: 任务回报失败后的产物交付
description: 任务已保存文件但总结请求被网关拒绝时，仍保留可信下载入口，并分别呈现任务真实状态和回报失败原因。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开后端与前端日志。公开控制输入见 `input/controls.json`，执行工具见 `tools.json`。本地 UDS 夹具不会读取节点模型设置或调用外部模型。
