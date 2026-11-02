---
name: 本机网关就绪与鉴权准入拒绝
description: 通过本地 UDS 重现网关关闭、密钥禁用和授权失效，检查零上游调用与不重试，并防止远端伪造或后续拒绝抹去先前未知用量。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开 `python.log`、`python.xml`、`frontend.log` 和 `frontend.json`。公开输入在 `input/controls.json`，依赖与测试入口见 `tools.json`。仅使用本地传输夹具，不读取节点模型配置、不调用外部模型。
