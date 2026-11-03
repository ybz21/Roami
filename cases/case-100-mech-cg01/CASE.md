---
name: 多轮会话的网关阻塞与内容评分分离
description: 在真实 Runtime 中注入可信的传输拒绝，确认未执行回合不进入 JSON 评分、阻塞原因进入汇总，保留前轮结果，并用错误内容与伪造错误码文本作反例。
---

运行 `python3 scripts/run.py --python /绝对路径/agent-runtime/.venv/bin/python --output /新的仓库外目录`。

先看 `receipt.json`，再展开 `tests.log`、`tests.xml`。输入列在 `input/controls.json`，原始多轮合同复用 Case95；只使用本地模拟传输，不读取节点配置或调用模型。
