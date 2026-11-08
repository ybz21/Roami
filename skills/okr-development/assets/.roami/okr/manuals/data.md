# 取数与确认入库

## 从 Skill 到事实

取数入口是 `connectors/<name>/SKILL.md`，脚本在其 scripts/，MCP 来源在 Skill 中写清账户、工具、字段与证据。先读确认的 metrics 和 Connector 绑定；同一来源多个字段尽量复用一次实际读取。来源失败不抹掉旧值，未取得的数据不是零。

数据成员把原始响应、截图、字段提取与候选请求保存在 `materials/YYYY-MM-DD/data/<简短主题>/`；任务/修订/运行身份写入清单。记录 source/account/item、单位、统计窗口、平台截至时间 as-of、实际采集时间及原始文件哈希；不要把“现在读到”误写成“现在的统计值”。只读采集不包含投稿、点赞或修改账号资料的权限。

## 确认方式

Main 先独立读取实际证据，核对语义、对象和窗口，再读取当前项目 revision。先完成缺失的 [指标与看板定义](dashboard.md)，然后使用宿主支持的 record 协议：

- 已绑定 Connector Skill：使用确认包摘要、来源身份、固定批次 id、窗口、values 和 evidence 的批次请求；读取宿主实际 connectorBatchProtocol，不猜字段。不确定上次是否成功时，按同一批次 id 查已有回执，不换 key 重复发布。
- 未绑定 manual 指标：开发 CLI 的单条格式为 `{"revision":CURRENT_REVISION,"metricId":"CONFIRMED_METRIC_ID","date":"YYYY-MM-DD","value":OBSERVED_NUMBER,"note":"SOURCE_AND_EVIDENCE"}`；将占位符换成真实值和正确 JSON 类型。Main 也可用项目操作的同一 record。每次写入后取返回的新 revision，不能沿用旧值连写。

开发终端命令：`roami project okr record <PROJECT_ID> --file <REQUEST_JSON> --json`。Connector/collect 的参数以已安装 `roami project okr help` 和当前上下文为准；不要试写生产端点来猜协议。不要直接修改 observations.jsonl、current.json、确认快照或运行时数据库。

## 保存后验收

回读确认的 observations，核对同 metricId、来源、日期、数值、单位和证据；保持此前全部历史。然后核对看板数据与实际卡片。来源原文明确显示 0 才记 0；完播率、平均观看时长等未提供时仍未知。候选文件、聊天里说“已取数”、已注册 Skill 都不等于确认入库，更不等于任务验收通过。

Main 将实际回执和来源映射写进团队记忆，将大文件和原始证据留在交付目录。不要把整个聊天或登录态复制进记忆。
