---
name: 本轮已读工作流的执行上下文
description: 用真实Native循环检查读取后的版本标记，验证权限、版本、遗忘与请求范围，避免重复注入Skill正文。
---

公开输入在 `input/workflow-reads.json`，严格运行器核对它与实际测试夹具逐字节一致。
运行 `scripts/run.py --output <仓库外新目录>`，先看receipt再展开tests.log。
42项零模型机制检查不代表原股票任务已采用Skill、质量通过或正式全套验收完成。
