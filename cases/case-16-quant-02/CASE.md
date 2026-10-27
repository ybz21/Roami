---
name: "策略参数选择"
description: "搜索均线参数并做样本外验证，不用测试集选参数。"
---

# QUANT-02

执行合同见 [case.json](case.json)。任务输入、前置条件、交付要求和硬断言均以该合同为准。

## 数据

公开输入：[180 根合成行情](inputs/prices.json)；来源与公式：[provenance.json](provenance.json)。
这不是实际市场行情。生成器只使用 Python 标准库，不下载数据：

```bash
python3 cases/case-16-quant-02/generate.py --output /tmp/quant-02-prices.json
```

运行时读取该输入，追加本次 receipt，再写入隔离工作区 `/workspace/prices.json`。
数据、工具说明和生成器的 SHA 会进入新套件；修改目录不会覆盖已经冻结的历史套件。

## 工具与运行

[tools.json](tools.json) 列出 Native Worker、文件工具、Shell、Python 3 与无网络要求。
[acceptance.md](acceptance.md) 说明切分、交付和验收。工具需求不会自行授予权限；实际可用工具由执行器统一限制。

现有装配入口：[corpus.py](../../agent-runtime/src/roami_agent/improvement/evaluation/corpus.py)，
数据与参考结果装配：[authored_fixtures.py](../../agent-runtime/src/roami_agent/improvement/evaluation/authored_fixtures.py)。
参考答案留在宿主判定器，不作为输入文件交给 Agent。

数据来源、输入文件、工具配置及判定位置见 [materials.json](materials.json)。运行状态以每次运行记录为准。
