---
name: 原评分与产物复核的证据绑定
description: 核对产物及原生快照在渲染、依据提取和评分前后的哈希，变更保持待复核并保留已发生用量。
---

公开输入位于input/artifact-sources.json，与实际测试夹具逐字节一致。脚本化渲染及评分仅测试机制，不代表真实质量；另有真实LibreOffice页面回归。
运行scripts/run.py --output <新的仓库外目录>，先读receipt，再展开tests.log。
