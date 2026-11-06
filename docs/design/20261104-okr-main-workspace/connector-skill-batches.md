# Connector Skill 批次确认

## Product Design

用户通过聊天定义来源、账号、指标、单位、窗口和采集方法，将采集工作放在项目
`.roami/okr/connectors/<source>/SKILL.md` 及其 Python/MCP 文件中。一个来源 Skill 可以
提供多个指标。原 Main 继续指挥原数据成员执行，读取证据后将整批结果确认入文件快照，
现有 HTML 看板通过只读 dataset 自动更新。运行态不新增配置页或插件入口。

来源定义、执行、数据发布、任务验收、外部发帖与日更调度分开。原 GitHub 兼容采集保持
其实际状态，直到新的日更运行者经独立验收；不把目录、Skill 文件或 autoCollect 当定时
任务。账号发布与调度时间问题未决时不推断许可。

## User Stories

- Main 确认同一来源 Skill 的多个指标，数据成员保存本轮原始响应后群聊回报。
- Main 核对证据后一次写入，未知网络结果用同一批次回执恢复，不产生重复计数。
- 变更代码/账号/窗口后先确认，失败保留旧事实；不把缺失数据填零。
- 更换数据库或重启服务后，原项目文件仍能恢复指标、证据与幂等回执。
- 编辑目标或看板时来源绑定保留，Main/成员实例与长期记忆不变。

## Technical Design

`Config.connectors[]` 保存 id/name/service/identity/timezone/window/files/bindings，
GitHub 另含 repo。Skill 文件相对其来源目录声明，宿主将摘要确认到 packageSha256。
Schema2 connector.json 只是来源与文件声明，不是 arbitrary-command 插件。它与 okr.json
一致后才能 sync，代码变更保持 pending。未绑定的旧 metric 目录与历史保留。

`backend/okr/connector-skills.go` 校验定义、包文件、来源键及变更确认；GitHub 复用既有
repoID/field sourceKey 以保留历史，其他来源将账号/字段/单位/时区/窗口纳入来源身份。
旧客户端省略 connectors 保留绑定，[] 表示显式解绑。普通单值接口不绕过已绑定来源。

`connector-batches.go` 扩展现有 POST observations 的 `{revision,batch}` 变体，CLI 仍为
`project okr record`，Python Main 的既有 `project_okr_update(operation=record)` 可直接
传递，继续限定项目身份，无需绕过旧运行时升级门禁。主机 capability 与自包含协议从
projectFiles 返回；旧内置 Skill catalog 不因此被假称升级。

每批使用持久 key、原 revision/payload，携带包摘要、来源身份、指标/单位、日期、真实
采集时间、snapshot/day 窗口及原始证据路径/SHA。宿主校验有限数字、绑定、时间窗口和
文件边界，保存内容寻址证据，将观测和 receipt 一起写入确认快照。JSONL 是导出视图，
current.json 是唯一提交点。未知结果只读查回执；并发或不确定结果不自动重放另一版本。

GitHub 原始响应须为同一公开 repoID/name，计数与提交值一致。通用/MCP 的 SHA 和身份
声明只能证明完整性及匹配确认定义，无法证明远端真实性或任意动态依赖已锁定；Main
必须核对真实账号/工具与口径。receipt 仅证明数据写入，受管任务仍走单独验收。

前端 configurationOf 保留绑定，编辑器显示来源名称，受管来源从 Main 调整，避免编辑
留下半套绑定；不新增用户配置面板。Main 消息快照提供真实 capability、绑定和宿主协议。
Skill 完整 assets/source 提案、GitHub/MCP parts 和候选准备脚本同步更新，复制不等于激活。

## 验收

当前隔离专项覆盖拒绝错误来源/单位/窗口/缺值/脚本变更、并发幂等、原始字节归档、
空数据库恢复、代码确认与旧客户端绑定保留。前端上下文/配置专项已通过。
正常 full、完整前端与独立 CLI/浏览器闭环待最终源码冻结后验收。真实项目尚未迁移，
没有开启新日程或发帖，没有操作手机。关联 #679。
