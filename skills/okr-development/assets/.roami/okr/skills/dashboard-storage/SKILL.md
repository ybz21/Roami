---
name: dashboard-storage
description: 初始化项目 SQLite 源库，按声明建表并事务写入、查询、导出和备份候选数据。
---

# 项目源库

用于 Connector 保存结构化采集明细。脚本只使用 Python 标准库，初始化为空库，不写示例事实。业务字段由项目决定，不固定为某个平台。

```bash
python3 .roami/okr/skills/dashboard-storage/scripts/sqlite_store.py --project-root "$PROJECT_ROOT" --project-id "$PROJECT_ID" init
```

使用真实项目根目录和宿主项目 ID；库在 `.roami/okr/data/source.sqlite3`，与发布登记 `collection.sqlite3` 职责不同。其他项目 ID、越界路径与不兼容版本会被拒绝。它仍是候选源库：宿主确认观测和当前看板继续通过受管 OKR 操作维护，HTML 不直接打开 SQLite。

## 定义业务表

将业务 schema 保存到 `.roami/okr/data/schemas/<名称>.json`。下例说明结构，不是实际观测；按项目来源、口径和单位填写，不用表名冒充已有数据：

```json
{
  "table": "src_records",
  "label": "来源明细",
  "key": ["object_id"],
  "columns": [
    {"id": "object_id", "label": "对象", "type": "string", "nullable": false, "unit": ""},
    {"id": "views", "label": "播放", "type": "integer", "nullable": true, "unit": "次"}
  ]
}
```

表名用 `src_`；字段支持 string/integer/number/boolean，声明 label、unit、nullable。逻辑键不能可空。来源身份、账号、日期与业务键共同识别记录，账号 ID 使用字符串，避免大整数截断。指标缺失为 null，实际返回的 0 保持 0。

```bash
python3 .roami/okr/skills/dashboard-storage/scripts/sqlite_store.py --project-root "$PROJECT_ROOT" --project-id "$PROJECT_ID" schema-apply --file "$SCHEMA_FILE"
```

回执提供 schemaDigest。重复应用幂等；允许添加可空字段，禁止自动删除旧列、改类型/单位/键。结构重解释先设计显式迁移、核验旧版与回退；不要直接 ALTER 或覆盖库。脚本物理表保存不可变行版本及完整字段 JSON，读取回执同时带声明的字段标签和单位。

## 事务写入与更正

Connector 保存真实响应到日期目录后，生成一个 UTF-8 请求文件：

- 根字段：`ingestKey`（该批持久键）、`schemaDigest`（当前建表回执）、`rows`。
- 每行完整字段：`values`（全部声明列；未知用 null）、`sourceIdentity`、`accountId`、`asOf`（YYYY-MM-DD）、`capturedAt`（真实带时区 ISO 时间）、`evidence`、`expectedVersion`。
- `evidence` 为 `{ "path": "项目相对路径", "sha256": "原始响应实际摘要" }`。脚本读取原始字节核验摘要；不把视频、Cookie 或凭据放进数据库。单份原始响应上限 4 MiB，大媒体另存文件。
- 新业务行 `expectedVersion: 0`。更正先 read，使用旧 rowVersion；脚本追加新版本，不修改旧行。一个批次不重复同一业务行。

```bash
python3 .roami/okr/skills/dashboard-storage/scripts/sqlite_store.py --project-root "$PROJECT_ROOT" --project-id "$PROJECT_ID" write --table "$TABLE" --file "$REQUEST_FILE"
```

一批最多 1000 行，整批短事务提交；任一字段、证据或版本不符，所有行和幂等回执回滚。同 ingestKey/内容重试返回原回执；同键改内容拒绝。未知提交结果先用原键对账，不换键重复写。不要以当前时间生成每次不同的重试键。

## 读取、导出和备份

```bash
python3 .roami/okr/skills/dashboard-storage/scripts/sqlite_store.py --project-root "$PROJECT_ROOT" --project-id "$PROJECT_ID" read --table "$TABLE" --source-identity "$SOURCE_IDENTITY" --account-id "$ACCOUNT_ID" --as-of "$DATE"
python3 .roami/okr/skills/dashboard-storage/scripts/sqlite_store.py --project-root "$PROJECT_ROOT" --project-id "$PROJECT_ID" export --table "$TABLE" --source-identity "$SOURCE_IDENTITY" --account-id "$ACCOUNT_ID" --as-of "$DATE" > "$CANDIDATE_EXPORT"
python3 .roami/okr/skills/dashboard-storage/scripts/sqlite_store.py --project-root "$PROJECT_ROOT" --project-id "$PROJECT_ID" backup --output "$PROJECT_RELATIVE_BACKUP"
```

read/export 使用只读连接，必须指定来源、账号、日期，默认每个业务键返回最新行；`--history` 保留所有版本。回执中的 recordKey/rowVersion/schemaDigest/sha256 固定候选，Main 验收时不可悄悄替换为后来新版本。旧行仍保存当时 schemaDigest 与原字段；新增可空列不回写旧证据。export 输出与 read 相同的候选 JSON，不是宿主已确认快照。

backup 使用 SQLite backup API 与 integrity_check，输出只能在本项目内且不能覆盖已有文件。发生错误保留原库与原请求，核对版本、证据和备份后再恢复。恢复旧备份前必须停止本项目写入并核对之后的新事实；不要用旧库覆盖已有新版本。坏批次更正采用新 ingestKey 和旧行版本继续追加，保留历史。

## 从源库到看板

源库回执明确为 candidateOnly，不是 Main 审批。原数据成员将固定行版本、原始证据与来源口径交 Main，按 `manuals/data.md` 和 Connector Skill 生成受管批次；Main 独立核验后走 record，回读确认修订并在真实页面检查数值。HTML 继续读取项目绑定的只读 SDK，不能读候选导出或发任意 SQL。

通用数据集发布、表格 SDK 与宿主 SQLite 权威迁移尚需各自实现验收；本脚本不宣称这些能力已经存在。现有发布登记、单稿/项目 Connector、确认指标历史不被此库替换。
