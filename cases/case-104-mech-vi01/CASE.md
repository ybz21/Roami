---
name: 视频时序预览与实际帧回执
description: 用真实编码素材验证可变帧率、非零起始时间、单帧与多视频流的抽帧、像素对应和安全发布，不把抽帧成功当作语义选片通过。
---

运行 `python3 scripts/run.py --image 已准备的本地镜像 --output 新的仓库外目录`。

先看 `receipt.json`，再看 `tests.log`、`junit.xml` 与 `frozen.json`。公开合成输入见 `input/recipe.json`，工具与环境见 `tools.json`。不读取节点模型配置、不调用外部模型。
