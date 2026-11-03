---
name: 原生任务保存模型能力的准入校验
description: 根据已保存的后台角色校验声明要求，覆盖主后台能力差异、未知和非布尔状态、CLI组合要求、执行前复核与旧任务兼容。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开 `python.log` 和 `python.xml`。输入为 `input/controls.json`，依赖与入口见 `tools.json`。模拟模型和执行器不调用外部模型，不读取或修改节点配置。
