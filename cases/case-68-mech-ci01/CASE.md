---
name: RSI 保存角色指令的容器传递
description: 节点保存的 Main、Worker 指令原样进入隔离 Actor；旧镜像启动前拒绝，固定判定镜像保留，不复制模型连接和密钥。
---

运行 `agent-runtime/.venv/bin/python cases/case-68-mech-ci01/scripts/run.py --output <新的仓库外目录>`。

数据见 `input/scenarios.json` 与测试中的合成配置；工具、来源和回执格式见本目录其他文件。零模型调用，不代表真实内容质量通过。
