---
name: 模型请求回执与重试用量
description: 用临时 Go 账本及真实 Unix 套接字验证请求关联、私有桥传递与未知用量保留；不调用真实模型、不修改正式配置。
---

来自 Issue #443 的脱敏扩展回归。`input/receipts.json` 给出两次 503 后一次成功的响应配方、虚构编号与成功用量；Python 测试实际读取此文件。Go 测试另建临时账本并核对响应编号。

- `tools.json`：实际执行的包、选择器和预期测试数量。
- `acceptance.md`：编号、状态、用量完整性、隐私与执行要求。
- `materials.json` / `provenance.json`：数据加载位置、来源及适用范围。
- `scripts/run.py`：冻结输入和实现 SHA，保存原始输出与执行回执，并清理本 Case 的隔离实例。

```bash
python3 cases/case-62-mech-rc01/scripts/run.py --output /tmp/roami-case-62-run
```

输出目录应放在仓库外，每次使用新目录。脚本拒绝空收集、失败、跳过、xfail 和漏执行；不把协议夹具称为真实模型任务验收。此 Case 独立运行，不加入原 authored-40 或正式 60 项，不覆盖历史成绩。
