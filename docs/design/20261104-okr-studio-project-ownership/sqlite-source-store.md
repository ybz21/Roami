# SQLite 源库实施

依据 [v1 契约](sqlite-v1-contract.md) 实现 #743 的结构化采集层。最终的确认状态迁移与表格 SDK 仍按原设计推进；本阶段不切换宿主存储权威，也不把发布登记脚本等同于通用源库。

## 用户操作

完整初始化模板增加 `skills/dashboard-storage/SKILL.md` 与标准库脚本。用户与 Main 讨论业务字段后，原数据成员可在项目中初始化空库、声明带 label/type/unit/nullability/key 的表，保存真实响应并事务写入，读取候选、导出和备份。新模板不带数据库二进制或示例观测。

## 模块与身份

`skills/okr-template.go` 在 Go 二进制中嵌入同一份 assets。宿主 `backend/okr/project-capabilities.go` 创建项目时只补齐缺失的通用 AGENTS、Main 指引、手册、项目 Skills、禁用日程提案与数据库忽略规则，不再维护另一份缩短的常量文本。用户 O/KR、页面、来源与真实身份仍由当前确认配置生成；不会复制模板占位 Connector、目标、观测或运行状态，也不覆盖已有项目定制。隐藏的 .roami 与 data/.gitignore 明确打包，Python 缓存不进入 Go 资源。

源库使用 `.roami/okr/data/source.sqlite3`，现有 `collection.sqlite3` 继续登记公开稿件，宿主确认数据仍走现有接口。原设计中的 `okr.sqlite` 是后续确认状态迁移目标，不能把源库改名冒充最终迁移。

脚本集中在 `dashboard-storage/scripts/sqlite_store.py`；不增加新的插件或 Python 依赖。`okr_source_meta` 绑定项目与脚本版本，`okr_source_schemas` 保留业务声明版本，`okr_source_ingests` 保存幂等请求及原回执。每个 `src_` 业务表保存完整字段 JSON、来源、字符串账号、日期、schema 摘要、业务键和不可变行版本。字段 label 与单位随读取结果返回，页面无需猜列名。

短写事务用 BEGIN IMMEDIATE：校验当前 schema、实际证据摘要与 expectedVersion，整批成功后提交行版本和幂等回执。重放已提交的相同 ingestKey 时，即使 schema 后来增加字段，也返回原回执；同键改内容冲突。再次取数或纠错追加新版本，Main 的旧候选仍固定原版。

建表只接收受限标识符，写入使用参数化值；不提供任意 SQL。默认 schema 变更只允许新增可空字段，不能重解释旧单位/键或删除字段。源路径、证据与备份限制在当前项目；这不是针对有本机文件权限用户的沙箱。

## 读取与恢复

read/export 使用只读连接，强制指定来源、账号、日期，返回明确的 candidateOnly 与固定版本；历史模式保留所有行。backup 使用 SQLite backup API 和 integrity_check，不覆盖旧备份。失败的批次全部回滚，不留下可被误认成成功的 ingest 回执。

源库输出经现有 Connector 批次与 Main 独立确认后才能进入指标 SDK。后续仍需完成通用 dataset 定义/发布/读取、宿主确认存储迁移与真实项目运行验收；当前新增脚本不是这些步骤的替代品。

## 验收

`agent-runtime/tests/test_okr_source_store.py` 从完整 assets 复制独立项目，用真实 CLI 检查空初始化、幂等、更正历史、schema 扩展、冻结旧版、并发写入 CAS、只读查询、账号/日期口径、未知/零值、非法字段与证据、整批回滚、越界路径及一致性备份。

Go 专项经实际 Store.Save 创建临时 OKR，检查规范资源完整、日程禁用、无示例事实、原项目定制保留、符号链接拒绝，并执行宿主复制出来的 Python 脚本初始化空库，再次保存不删除源库。不以打包清单代替实际创建入口验收。

真实项目在原 Main 独立核验并续派原数据成员后初始化；开发测试不能填入它的业务库。最终验收仍需真实源库 → 固定候选 → Main 确认 → 实际看板 → 复盘/下一轮的完整回执。
