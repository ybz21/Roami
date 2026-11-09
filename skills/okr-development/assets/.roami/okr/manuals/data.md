# 取数与确认入库

## 从 Skill 到事实

取数入口是 `connectors/<name>/SKILL.md`，脚本在其 scripts/，MCP 来源在 Skill 中写清账户、工具、字段与证据。先读确认的 metrics 和 Connector 绑定；同一来源多个字段尽量复用一次实际读取。来源失败不抹掉旧值，未取得的数据不是零。

数据成员把原始响应、截图、字段提取与候选请求保存在 `materials/YYYY-MM-DD/data/<简短主题>/`；任务/修订/运行身份写入清单。记录 source/account/item、单位、统计窗口、平台截至时间 as-of、实际采集时间及原始文件哈希；不要把“现在读到”误写成“现在的统计值”。只读采集不包含投稿、点赞或修改账号资料的权限。

## 确认方式

Main 先独立读取实际证据，核对语义、对象和窗口，再读取当前项目 revision。先完成缺失的 [指标与看板定义](dashboard.md)，然后使用宿主支持的 record 协议：

- 已绑定 Connector Skill：使用确认包摘要、来源身份、固定批次 id、窗口、values 和 evidence 的批次请求；读取宿主实际 connectorBatchProtocol，不猜字段。不确定上次是否成功时，按同一批次 id 查已有回执，不换 key 重复发布。

支持 `swarm_connector_batch` 的宿主上，Main 可用 `roami swarm connector batch --input '{"swarmId":"实际团队ID","batchId":"实际批次ID"}'` 直接读取确认回执；当前修订与原回执修订分别保留。旧宿主读取完整 project context 留存文件，不能只看截断预览。`confirmed` 表示已经入库；同键改 note、刷新 CAS 或改变窗口仍会冲突，但不撤销旧事实。新作品扩充集合后另做真实新采集，不把旧快照叫作“作废”。回执 requestSha256 是宿主类型化请求摘要，不等于 batch-request.json 的文件 SHA 或自行排序后的 JSON 摘要；证据文件摘要仍须与真实字节核对。
- 未绑定 manual 指标：开发 CLI 的单条格式为 `{"revision":CURRENT_REVISION,"metricId":"CONFIRMED_METRIC_ID","date":"YYYY-MM-DD","value":OBSERVED_NUMBER,"note":"SOURCE_AND_EVIDENCE"}`；将占位符换成真实值和正确 JSON 类型。Main 也可用项目操作的同一 record。每次写入后取返回的新 revision，不能沿用旧值连写。

开发终端命令：`roami project okr record <PROJECT_ID> --file <REQUEST_JSON> --json`。Connector/collect 的参数以已安装 `roami project okr help` 和当前上下文为准；不要试写生产端点来猜协议。不要直接修改 observations.jsonl、current.json、确认快照或运行时数据库。

## 保存后验收

回读确认的 observations，核对同 metricId、来源、日期、数值、单位和证据；保持此前全部历史。然后核对看板数据与实际卡片。来源原文明确显示 0 才记 0；完播率、平均观看时长等未提供时仍未知。候选文件、聊天里说“已取数”、已注册 Skill 都不等于确认入库，更不等于任务验收通过。

Main 将实际回执和来源映射写进团队记忆，将大文件和原始证据留在交付目录。不要把整个聊天或登录态复制进记忆。

## 新稿自动参与取数

用 [collection-store](../skills/collection-store/SKILL.md) 初始化项目 SQLite 并登记 Main 已审核的实际公开稿件。Connector 按已确认账号查询登记、重新核验平台身份、记录完整覆盖集合；新增稿件不修改 Skill 代码包。保留旧单稿指标，新增“本项目已核验稿件累计”口径；不同覆盖集合的快照不能直接相减声称日增量。数据库写入不是发布看板，候选仍按上文验收确认。当前脚本只提供登记操作，不能当作任意 SQL 或宿主观测写入入口。

## 结构化采集源库

需要按业务表保存明细时，读取 [dashboard-storage Skill](../skills/dashboard-storage/SKILL.md)，使用其 init、schema-apply、write、read/export、backup。它初始化空的 source.sqlite3，业务字段在项目声明，物理源表保存不可变行版本；按来源、字符串账号 ID、日期和业务键隔离。新采集采用持久 ingestKey 与当前 schemaDigest；更正检查 expectedVersion，整批失败回滚，原始证据按实际字节核验。未知用 null，真实 0 不丢失；不得把累计快照相加当增长。

Main 读取固定行版本与原始证据，再按已支持的 Connector 批次确认入库。此源库不替换旧观测或宿主确认修订；导出仍是候选，前端继续只读 SDK。数据库备份用 Skill 的 SQLite backup 操作，不只复制 WAL 主文件；恢复前先核对后来事实，不能用旧备份盖掉新行。完整模板复制后包含此 Skill，不包含生成的数据库或示例业务数据。
