---
name: 非对象模型JSON的动作隔离与队列续办
description: 错误模型JSON只阻断当前动作，保留回执与用量，后台队列继续工作，恢复不重放。
---

公开数组、null、数值、字符串和布尔样例见input/model-result-shapes.json，测试逐项读取；使用真实ResearchWorker、私有SQLite和脚本化模型，没有实际模型或人工评分。运行scripts/run.py --output <新的仓库外目录>，先看receipt，再展开tests.log。
