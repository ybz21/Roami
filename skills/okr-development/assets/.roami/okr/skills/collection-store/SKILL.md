---
name: collection-store
description: 初始化本项目的 SQLite 发布登记，供 Connector 发现已核验稿件。
---

# 发布登记

只登记 Main 已独立审核的实际公开稿件。发布者的自述、发送按钮点击和上传成功都不能代替公开证据。此库是项目采集目录，不是宿主已确认的 OKR 数据库；写入后仍须取数、Main record 与真实看板验收。

脚本只使用 Python 标准库。复制完整模板后，以项目真实根目录和 ID 初始化，不使用示例 ID：

```bash
python3 .roami/okr/skills/collection-store/scripts/collection_store.py --project "$PROJECT_ROOT" --project-id "$PROJECT_ID" init
```

初始化创建 `.roami/okr/data/collection.sqlite3`，自动建立 metadata 与 publications 表。不要复制其他项目的数据库；不要把生成的数据库提交进通用模板。重复初始化保留记录，其他项目 ID 会被拒绝。

Main 审核公开事实后，将以下字段写成 UTF-8 JSON：businessKey、platform、accountId、objectId、url、publishedAt、mainReviewReceipt、evidenceSha256。全部为非空字符串；时间使用带时区的 ISO 时间；摘要是实际原始证据文件的 SHA-256，回执来自真实 Main 验收。不得编造回执以通过校验。脚本验证存储结构，不能证明平台公开状态或回执真实性，Connector 和 Main 仍须独立核验。

```bash
python3 .roami/okr/skills/collection-store/scripts/collection_store.py --project "$PROJECT_ROOT" --project-id "$PROJECT_ID" register-publication --file "$REVIEWED_PUBLICATION_JSON"
python3 .roami/okr/skills/collection-store/scripts/collection_store.py --project "$PROJECT_ROOT" --project-id "$PROJECT_ID" list-publications --platform bilibili --account-id "$CONFIRMED_UID"
```

同业务键同内容幂等；同平台、账号、稿件不能重复登记。修改证据或时间时先读取已有 sha256，再传 `--expected-sha256`，防止覆盖其他成员修改。平台、账号、稿件身份不可变。改正误登记的流程交 Main 设计，不能删除历史或换业务键绕过冲突。

更正会保留不可变的历史版本。用同一脚本的 `publication-history --business-key "$BUSINESS_KEY"` 读取版本、内容及摘要；已冻结候选保留原版本，不能在验收时改用最新登记。

Connector 按确认账号过滤，逐项调用公开来源验证对象身份。保留返回的 coverageSha256 及完整覆盖集合；登记数据不是采集结果。聚合口径必须叫本项目已核验稿件集合，不是全账号。缺失值保持未知，不能以零代替。脚本目前只提供发布登记；候选批次与指标仍按已有 Connector batch 协议生成和确认，没有新增任意 SQL 入口。

扩展表结构时先在项目 Skill 中设计字段、唯一键、迁移和回滚，增加显式操作与参数化 SQL，保持 schemaVersion 兼容检查。不要让模型直接对宿主 project-okr.db、模型账目库或确认导出执行 SQL。数据库不存登录态、令牌或视频文件。

## 日发布量

按项目时区和平台实际 `publishedAt` 统计，不能把登记集合覆盖数、采样日期或素材目录日期当作今天发布量。使用配对参数：

```bash
python3 .roami/okr/skills/collection-store/scripts/collection_store.py --project "$PROJECT_ROOT" --project-id "$PROJECT_ID" list-publications --platform bilibili --account-id "$CONFIRMED_UID" --published-on "$PROJECT_DATE" --timezone "$PROJECT_TIMEZONE"
```

`registeredCount` 是账号集合覆盖数，`publishedCount` 是该时区该自然日的去重对象数；每条 `publishedAt`、来源证据摘要和筛选集合摘要保持可查。默认不加日期参数仍返回原全部集合，Connector 口径不变。未知、无时区、摘要不符或冲突时间须先核对来源，不能改成0。查询结果仍是候选，不自动发布确认观测，也不授予新发布权限。只登记了 B站时不能声称自动覆盖 X；其他渠道需要其真实公开回执和已审核登记。

`scope=registered-project-publications` 明确只统计本项目已登记集合，`accountDailyCountKnown=false` 表示它不能证明全账号当天总量。空集合中的0不证明账号未发布；尚未登记的渠道须先核对其真实回执，不能据此重新发布。
