---
name: 部分评分的回执与汇总
description: 后续评分失败或中断时保留已完成评分，显示完成数量，维持待复核且不重放请求。
---

公开合成响应见input/partial-artifact-ratings.json。评分者、校准参考与图像均为脚本夹具，不是实际模型、人类标签或可用图像。运行scripts/run.py --output <新的仓库外目录>，先看receipt，再展开tests.log。
