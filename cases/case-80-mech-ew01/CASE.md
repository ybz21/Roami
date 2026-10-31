---
name: 已存在执行窗口的上下文传播
description: 复现评测外层窗口未传给模型，验证协调和Native工具循环看到真实剩余时间，同时保留节点路由和不限任务配置。
---

# MECH-EW01

`input/timing-scenarios.json` 由实际测试直接读取；`tools.json` 列出工具和50项检查。
执行 `scripts/run.py --output <仓库外新目录>`，先看receipt，再展开tests.log。
这是机制回归，零外部模型调用，不代表视频选片或正式全套通过。
