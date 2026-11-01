---
name: 评分对象形状校验与已完成回执保留
description: 维度数组和坏评分记录只产生明确的待评分错误，保留先前盲评及合成用量，坏校准输入在调用模型前拒绝。
---

输入见input/rater-contract-shapes.json，由测试逐项读取；使用真实ArtifactReviewer及私有JSON回执、脚本化评分模型，无真实模型或人工评分。运行scripts/run.py --output <新的仓库外目录>，先看receipt，再展开tests.log。
