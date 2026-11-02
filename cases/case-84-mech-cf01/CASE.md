---
name: 容器失败的私有错误证据
description: 保留退出码和裁剪脱敏后的标准错误，传递至Case证据，保证并行隔离且不自动重放。
---

输入见input/container-failures.json；其中错误为公开合成数据。机制检查另运行真实只读Docker失败，不能记为任务质量成绩。运行scripts/run.py --output <新的仓库外目录>，先看receipt，再展开tests.log。
