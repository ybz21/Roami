---
name: 本地 Skill 完整目录执行
description: 本地配置的外挂 Skill 通过返回的资源目录执行脚本、读取二进制素材并交付文件，禁用和目录边界仍生效。
---

使用 `agent-runtime/.venv/bin/python cases/case-65-mech-sp01/scripts/run.py --output <新的仓库外目录>` 运行。

`input/scenarios.json` 列出公开材料与来源；脚本冻结本次代码、输入和测试入口，在私有 tmux 服务中执行，保留 JUnit、日志与测试生成的实际 PPTX。结果只证明确定性加载、执行及交付合同，不证明模型自主完成任务。
