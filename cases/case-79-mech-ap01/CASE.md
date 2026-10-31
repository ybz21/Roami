---
name: 前台Agent Runtime随父进程结束
description: 复现Go前台serve被TERM或KILL终止后遗留Python进程，验证既有父管道协议和私有进程清理。
---

# MECH-AP01

数据见 `input/scenarios.json`，实际Go测试直接读取该文件。工具和依赖见 `tools.json`，运行入口见 `scripts/run.py`；结果先看receipt，再展开tests.log。零模型调用，不代表音视频质量通过。
