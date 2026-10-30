---
name: 大工具回调与待确认产物交付
description: 专业智能体读取长文档并交付单页 HTML；完成回调过大或对账未完成时，已有回报和文件仍可查看，任务不能被伪造为成功。
---

来自 [Issue #523](https://github.com/ybz21/Roami/issues/523) 的脱敏机制回归。现场存在 HTML 和两张截图，任务仍显示执行中，执行轮次为 unknown；4 个 Read 完成回调因 CLI 通用输入上限而丢失。

本 Case 使用生成的工具响应、合成 HTML 和脚本化执行回执，不调用真实模型，也不验证 SpaceX 研究结论。

- `input/incident.json`：场景、事件顺序和故障条件；大响应在测试中生成，不把大文件复制进仓库。
- `tools.json`：Go、Python 测试入口与隔离条件。
- `acceptance.md`：必须满足的状态、文件与防重放要求。
- `scripts/run.py`：独立执行 Go 与 Python 回归，冻结合同和资源 SHA，并保留逐项输出与 receipt。

```bash
python3 cases/case-61-mech-vd03/scripts/run.py --output /tmp/roami-case-61-run
```

需要仓库 checkout 中的 Go、uv 和已安装测试依赖。执行器使用仓库隔离入口，不拿用户 tmux、任务或账本作夹具。缺少工具或任一测试失败都不能记为通过。

这是扩展回归 Case，单独保留运行结果，不加入原 authored-40 或正式 60 项，也不覆盖其冻结合同或历史成绩。重复运行使用新输出目录。
