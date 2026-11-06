---
name: source
description: 按本项目已确认的来源、账号和时间窗口采集指标候选事实。
---

先读取当前项目 context 与 connectors 来源绑定。这个目录是待填写的通用提案，默认
配置尚未绑定它；先通过对话确定实际来源、账号、字段、单位、时区和 snapshot/day
窗口，再组合 Python 或 MCP parts，声明全部复核文件，交 Main 保存确认包摘要。
不要用占位符执行、造数或开启日程。

在本成员真实工作目录使用已授权的 Python/MCP 能力取数，保存原始响应、稳定来源
身份、时间窗口和摘要，回报原 Main。缺数保持未知，不填零或直接覆盖数据文件。

若 projectFiles.connectorSkillBatches=true，按其 connectorBatchProtocol 准备批次，
由 Main 阅读当前轮证据后通过 operation=record、payload={revision,batch} 确认。
批次 key 只生成并保存一次，未知结果先查 connectorBatches 再重试原请求。回执不
等于任务验收、发布成功或每日调度。旧宿主不支持时保留提案，不绕过能力边界。
