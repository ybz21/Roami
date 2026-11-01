---
name: 源快照统计比较与变化率
description: 按明确选择的统计量比较两份CSV，给出来源哈希、差值和变化率，验证输入不变且零基数不虚构百分比。
---

输入在input/，对应真实执行的测试夹具；工具与公式见tools.json、materials.json，来源见provenance.json。运行scripts/run.py --output <新的仓库外目录>，先看receipt再展开tests.log；这是机制检查，不是股票原题或人工质量评分。
