---
name: 外挂行情报告的事实、图表与最终渲染
description: 用公开跨年行情验证收益、回撤、日历分组和同日相关口径，检查原始字段丢失时拒绝发布，并实际渲染保存后的九页报告；不调用模型或改写正式套件成绩。
---

先准备满足 `tools.json` 的本地测试镜像，再运行：

```sh
python3 scripts/run.py --image <本地镜像ID> --output <新的仓库外目录>
```

先看 `receipt.json`，再展开 `tests.log` 和 `tests.xml`。输入在 `input/`，实际代码和测试在 `skills/market-series-report/`；不依赖隐藏答案、行情账户或真实模型。
