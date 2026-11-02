---
name: 外挂 Skill 的初始发现
description: 初始工具信息显示已启用外挂的名称、用途和读取路径，正文按需读取，导入、更新和禁用即时生效。
---

运行 `agent-runtime/.venv/bin/python cases/case-66-mech-sd01/scripts/run.py --output <新的仓库外目录>`。

材料与测试入口见 `input/scenarios.json` 和 `tools.json`。保存冻结哈希、JUnit、日志及真实生成的 PPTX；脚本化模型只验证工具信息和通用执行交付合同，不作为自主模型质量成绩。
