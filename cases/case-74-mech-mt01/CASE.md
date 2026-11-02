---
name: 模型传输失败位置与脱敏证据
description: 区分连接、响应头和响应体读取失败，将安全类型写入实际Agent执行记录，保留原重试与用量未知状态。
---

`input/failures.json` 是公开合成错误配方，与实际测试读取的 `agent-runtime/tests/fixtures/model-transport-failures.json` 逐字节一致；运行器先校验两者。Runtime测试保留自包含输入，固定镜像不依赖完整Case库或私有判定材料。

测试使用明确的本地HTTP替身和真实Agent持久化链路，不调用外部模型。`scripts/run.py` 冻结素材、实现和测试，保存JUnit及严格回执。
