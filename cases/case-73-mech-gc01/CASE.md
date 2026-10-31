---
name: 空模型连接与截断请求分类
description: 真实本地Unix连接不发送数据即关闭不算模型失败；截断HTTP请求、真实模型认证错误仍保留。
---

`input/requests.json` 是测试实际发送的四种HTTP字节配方，不含真实请求或密钥。测试使用本地私有Unix socket和伪Provider，不调用外部模型。

`scripts/run.py` 冻结源码、测试及素材，保存JUnit和严格零跳过回执；不改正式60项历史套件。
