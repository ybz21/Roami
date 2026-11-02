---
name: "演示文稿位置与绘制顺序"
description: "读取嵌套文本框在幻灯片中的位置，区分绘制顺序与从上到下的选框顺序。"
---

# MECH-DL01

合同见 [case.json](case.json)，实际输入参数和断言见 [input/layout.json](input/layout.json)，工具见 [tools.json](tools.json)，数据生成来源见 [materials.json](materials.json)。可以包含多个组合形状；不调用真实模型。

在仓库环境执行 `uv run --project agent-runtime python cases/case-63-mech-dl01/scripts/run.py --output /tmp/唯一的新目录`。输出包含最小 OOXML 样本、读取结果、测试输出、冻结哈希和执行回执。该回归不加入原正式 60 项。

解析和位置计算由可选 presentation-edit Skill 提供，基础 read 仅返回原始字节。此 Case 的最小 OOXML ZIP 只验证结构，不证明可编辑文稿或模型任务通过。
