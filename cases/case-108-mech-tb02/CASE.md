---
name: 结束工具混合批次的零副作用纠错
description: 检查四类结束工具的批次独占、失败回执、纠正继续与重复停滞，同时保留有效动作、读取、提问和原生续跑。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开 `python.log` 和 `python.xml`。`input/controls.json`提供工具参数、顺序与合法动作数；`tools.json`列出18项选择和依赖。使用模拟提供方和私有SQLite，不调用节点模型或系统Shell。
