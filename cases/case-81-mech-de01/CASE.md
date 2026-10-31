---
name: 成品交付与内部执行证据
description: 复现内部日志自动成为附件、链接按时间排序以及输入简称误报缺失，验证真实Runtime交付和文件边界。
---

# MECH-DE01

公开数据在 `input/delivery-evidence.json`，与实际测试读取的fixture逐字节核对。
工具和114项检查见 `tools.json`，运行 `scripts/run.py --output <仓库外新目录>`。
先看receipt，再展开tests.log。零外部模型调用；不代表原生视频语义或正式全套通过。
