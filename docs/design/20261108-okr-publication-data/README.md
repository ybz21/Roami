# 发布后的动态取数

关联 #743、#761。本设计是 [项目源库方案](../20261104-okr-studio-project-ownership/sqlite-data-design.md) 的过渡阶段，沿用其 [不可变版本契约](../20261104-okr-studio-project-ownership/sqlite-v1-contract.md)。发布登记脚本先解决真实闭环中的新稿发现，不代表通用 schema apply、源表批量写入、批准数据集或 SQLite 发布权威迁移已完成；#743 不能因此关闭。

## Product Design

发布新稿后，数据智能体应自动发现本项目已确认的稿件、取数并交给 Main 验收，无需为每条新稿重新配置 Connector。看板区分单稿累计量与本项目已核验稿件的累计量，展示覆盖稿件及采集时间。未知值不显示为零；部分稿件失败时保留上次已确认数据，不把残缺合计冒充完整合计。

本次设计源于真实缺口：新视频 BV1CvWH6wEXn 已公开，但现有 B站 Connector 只绑定旧稿 BV1xp4i6EEsp。新稿候选数据不能写进旧稿指标。现有模板还缺少用户要求的通用 SQLite 初始化与写入脚本。

## User Stories

- Main 独立审核实际发布事实后登记稿件；重复登记不产生重复对象。
- 数据成员读取登记集合，按同一账号逐项核验公开接口，输出带来源和覆盖集合的候选批次。
- Main 验收后确认批次，并从实际看板核对结果；本地 SQL 写入不等于看板更新。
- 后续 OKR 复制完整模板后，能够按手册初始化自己的数据库、登记对象与保留采集历史。

## Technical Design

### 两类存储

项目目录 `.roami/okr/data/collection.sqlite3` 保存发布登记、Connector 运行及候选证据索引。初始化脚本使用 Python 标准库 sqlite3，绑定真实项目 ID；不随模板提供生成后的数据库。项目 Skill 操作此库，不接受主机运行库路径。

主机现有 `project-okr.db` 保存已确认的 OKR 状态及操作回执。仍通过版本检查的 save/sync/record 入口更新，不直接写 SQL。JSONL 和 state/current.json 是主机导出，不新增第二个导入入口。

自定义 HTML 继续通过 `okr.ready()`、`okr.data.read(metricId)` 与 subscribe 读取已确认、已声明的数据。不得直接读项目 SQLite、执行 SQL、访问主机路径或携带平台凭据。此设计不新增前端数据库访问能力。

### 模块与数据

通用模板增加独立的 collection-store Skill 和 `scripts/collection_store.py`，提供 init、register-publication、list-publications、record-candidate 等明确操作，不提供任意 SQL 执行。SQL 参数化；数据库路径限制在本项目 data 目录；初始化和后续操作检查 projectId。对象唯一键包括平台、账号与平台对象 ID；业务键独立唯一。同键同内容幂等，冲突更新必须带旧内容摘要，事务内比较后提交。凭据不入库。

首个增量仅交付 init/register-publication/list-publications，候选批次继续使用现有协议。登记更正追加 publication_versions，旧内容摘要与版本可追溯，当前索引只用于发现最新登记，不替换已冻结的审核证据。后续通用源表实现按原契约继续追加版本。

发布登记保留 businessKey、platform、accountId、objectId、公开 URL、公开时间、Main 审核回执和证据摘要。候选保留 runKey、sourceId、capturedAt、覆盖对象集合摘要、原始证据引用与候选摘要。原始证据留在按日期组织的项目物料目录，数据库不吞入视频和音频。

B站聚合 Connector 使用稳定的项目及账号身份。登记库属于可变数据，不放进 Connector 代码包摘要。每次发现新对象无需修改已确认 Skill；账号及指标口径变化仍需重新确认。保留旧单稿六项指标，新增明确命名的“本项目已核验稿件累计播放”等指标，禁止静默替换原口径。

所有计数验证为非负整数，拒绝布尔值；明确观测到的零保留，缺失为 unknown。聚合批次记录完整覆盖集合；不能用两个不同覆盖集合的快照相减声称当天增长，也不能将项目稿件集合称作全账号总量。

### 实际接入顺序

先交付模板及脚本的隔离验证，再由原 Main 通过已有开发入口确认新来源、指标和 HTML 声明。由 Main 审核已有真实发布证据，交原数据成员登记并重新取数；Main record 后读取真实看板，随后记忆与复盘。保留原 Main、原成员和历史，不重新发布已有内容。

`parts/connectors/bilibili/scripts/bilibili_project.py` 与既有单稿脚本一同打包，复用匿名 GET、公开状态/账号/稿件身份及原始字节校验。SQL 登记读取为 query_only。每次输出固定覆盖集合；prepare 离线重算每一份证据和合计，匹配确认的项目、Skill、指标映射及 snapshot 窗口。单稿脚本和原单稿配置保持兼容。SQLite 登记不携带 Skill 代码，更不替代宿主准入或 Main 语义验收。

## Acceptance

待实现、待验收，以上不是已执行结果。要求项目隔离、初始化重复调用、同键幂等、CAS 冲突、跨账号拒绝、零和未知、部分采集失败、集合摘要、已确认 HTML 数据链路的专项验证。最终必须有原 Main 实际验收回执和页面数值证据，才能声称新稿进入看板。

2026-11-08：发布登记和项目集合 Connector 的初版隔离实现已完成，相关专项（含既有单稿与完整模板包）61 项通过。覆盖跨项目/账号拒绝、动态发现、幂等/CAS、历史版本、零/未知、原始字节篡改、覆盖集变化及单稿失败不输出残缺合计。此记录不代表已合入、部署或真实项目采集/看板通过；仓库完整门禁与真实 Main 验收仍待完成。

完整提交检查首次在上海午夜跨日，两个既有日期槽回归使用模块导入时冻结的 DAY，与执行时真实日期不一致而失败（其余 4436 项通过）。修正为每个测试执行前取当前日，生产日期过期检查保持原样；35 项日期槽/新数据专项通过，正常提交检查重新执行。不把这次失败记为质量通过。
