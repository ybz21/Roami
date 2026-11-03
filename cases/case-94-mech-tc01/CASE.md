---
name: 原任务续作的附图来源与恢复说明
description: 验证旧审计副本缺图时沿真实来源恢复，连续续作保留输入与原执行器，版本冲突和未知结果给出正确恢复边界。
---

执行 `uv run --frozen --project agent-runtime python cases/case-94-mech-tc01/scripts/run.py --output .roami/rsi-task-recovery/mech-tc01`（仓库根目录）。输出目录必须尚不存在。先看 `receipt.json`，再看 JUnit、原始日志与 `frozen.json`。

合成输入由已冻结的测试生成，选择清单由本Case实际读取；使用真实Runtime/SQLite及本地CLI或进程协议夹具，不调用生产服务、真实绘图或其他外部模型。独立扩展机制Case，不改写历史40/60项套件。

本项是需要源码检出的宿主机制回归，不通过普通Agent对话启动，不计入正式模型评测成绩。
