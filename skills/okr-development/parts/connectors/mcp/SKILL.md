---
name: mcp
description: 使用已经授权的 MCP 来源采集本项目确认口径的候选指标。
---

先发现可用 MCP 连接、工具 schema/effect、账号与资源。按本项目确认的指标映射取数，
保留日期、窗口、单位、账号、原始证据与实际工具回执。缺少连接/授权时保持未知；
不换账号、不猜工具名、不把工具目录当作已取得数据。

读取 references/source-binding.md，填入真实连接及字段约定。输出候选观测供宿主
验证与发布，不直接写确认快照或运行数据库。定时启用必须有真实调度回执。

宿主 connectorSkillBatches=true 时，将本包与 references/source-binding.md 列入确认
的 files，source/account 绑定到 identity。成员保留真实响应文件与本轮回执，Main
阅读后依据 connectorBatchProtocol 通过 record 批次确认；哈希不能代替账号和口径
复核。没有该能力时保留候选，不把手写文件当已发布数据。
