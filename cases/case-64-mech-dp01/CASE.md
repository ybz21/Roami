---
name: 外挂文稿编辑与交付
description: 完整外挂 Skill 包通过通用导入、读取、执行和交付机制编辑独立 PPTX，不向基础工具加入格式专用接口。
---

使用 `agent-runtime/.venv/bin/python cases/case-64-mech-dp01/scripts/run.py --output <新的仓库外目录>` 运行。

数据配方在 `input/recipe.json`，工具及严格回执合同见 `tools.json`、`materials.json` 和 `acceptance.md`。结果目录保留实际输入、编辑后 PPTX、读取 JSON、命令回执和代码哈希。无真实模型调用，不属于正式质量成绩。

单页检查的12页实际配方见 `input/focused-slides.json`；79项独立包检查及1项真实交付合同，共80项，零跳过。

文本替换数据见 `input/text-replacement.json`：公开合成的混合字体样式、精确替换及期望结果。运行器额外执行真实 CLI 并保留输入、输出与回执。
