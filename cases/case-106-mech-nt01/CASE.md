---
name: 原生验收的管理命令与用户追问续跑
description: 检查内部管理命令可达、Main系统shell仍禁用、用户追问复用任务和工作区，以及不同执行权限的缓存隔离。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开 `python.log` 和 `python.xml`。输入为 `input/controls.json`，工具、构造器模拟边界和11项选择见 `tools.json`。使用模拟提供方，任务、工作区文件和版本推进真实执行；不读取节点配置，不调用外部模型。
