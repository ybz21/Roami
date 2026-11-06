---
name: bilibili
description: 读取已确认 BVID 与 UP 主的公开累计统计，准备带原始证据的 OKR Connector 批次候选。
---

读取项目确认的 Connector、BVID、UP 主 MID、指标映射和时区。本 Skill 只读公开
视频的播放、点赞、弹幕、评论、分享、收藏累计数，不读登录态，不投稿，不含完播率、
平均观看时长、全账号总量或每日增量。缺失字段仍未知，来源明确返回 0 才是零。

复制本包到项目 `.roami/okr/connectors/<id>/`，声明实际文件
`["SKILL.md", "scripts/bilibili.py"]`；service 为 bilibili，identity 为
`bilibili:<UP主MID>:<BVID>`，window 为 snapshot，timezone 为项目确认的 IANA 时区。
bindings 将 manual 指标分别映射到 view、like、danmaku、reply、share、favorite。
不要把示例占位符当来源；由 Main 通过当前 revision 的 save/sync 确认代码摘要。
绑定旧 manual 指标会切换当前来源，旧观测保留在历史，需发布新来源的批次再验收页面。

在原数据成员当前任务/修订/运行交付目录执行：

```bash
python3 scripts/bilibili.py fetch --bvid CONFIRMED_BVID --owner-mid CONFIRMED_MID \
  --timezone CONFIRMED_IANA_TIMEZONE > CANDIDATE_FILE
```

仅 exit 0 且完整解析 stdout 才取得候选。脚本单次匿名 GET，不跟随重定向，检查
HTTP200、API code0、视频公开状态、BVID、MID 与 aid；保留响应原 UTF-8 字节、SHA256
及公开时间/类型响应头。capturedAt 是采集时间；asOf 是其在确认时区的日期，不保证
平台统计实时更新。HTTP 失败、限流、身份变化或不完整响应保留旧事实，不反复绕过。

原 Main 独立读取原始 evidence.http.body 并重算 SHA，核对账号/视频及累计口径。
读取当前 workspace 和 connectorBatchProtocol；支持 connectorSkillBatches 时，用一个
已保存的 32 位小写十六进制批次 key 准备候选（路径相对项目，置于当前交付目录）：

```bash
python3 scripts/bilibili.py prepare --workspace WORKSPACE_FILE --candidate CANDIDATE_FILE \
  --connector CONFIRMED_CONNECTOR_ID --batch-id PERSISTED_BATCH_KEY --project PROJECT_ROOT \
  --evidence DELIVERY_DIR/response.raw.json --output DELIVERY_DIR/batch-request.json
```

prepare 离线复核来源、原始字节、字段、单位、日期与确认包摘要，只写原响应和请求，
同路径相同字节可重放，不覆盖不同文件。Main 审核后按宿主 record 协议发布，回读批次
回执和真实看板。未知提交结果先查原 key，不能换 key 或只更新 revision 重放。
批次摘要仅证明完整性，不证明远端真实性；当前宿主的通用来源仍需要 Main 语义验收。

复用原 Main、原数据成员与原任务，失败先对账，不开替代实例。日更须另有用户确认时间、
真实调度安装/nextDue 和运行记录；本 Skill 不启用定时，不写确认文件或运行时数据库。
