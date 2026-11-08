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

## 项目稿件集合

需要每条新稿自动参与取数时，保留已有单稿来源和历史，另建项目集合来源。复制本包时
声明三个文件 `SKILL.md`、`scripts/bilibili.py`、`scripts/bilibili_project.py`。身份为
`bilibili:<确认MID>:project:<真实项目ID>`，service 仍为 bilibili、window 为 snapshot。
新增明确命名的“本项目已核验稿件累计”指标，不把它改称全账号总量或日增量。

原 Main 审核实际公开事实后，按完整模板的 collection-store Skill 登记稿件。SQLite
登记库在项目 data/，属于可变数据，不加入 Connector 代码包；新增稿件不会改变包摘要。
登记中的 Main 回执和摘要只是索引，不能替代 Main 独立读取真实公开证据。

```bash
python3 scripts/bilibili_project.py fetch --project "$PROJECT_ROOT" --project-id "$PROJECT_ID" \
  --owner-mid "$CONFIRMED_MID" --timezone "$CONFIRMED_TIMEZONE" > "$CANDIDATE_FILE"
python3 scripts/bilibili_project.py prepare --project "$PROJECT_ROOT" \
  --workspace "$WORKSPACE_FILE" --candidate "$CANDIDATE_FILE" --connector "$CONNECTOR_ID" \
  --batch-id "$PERSISTED_BATCH_KEY" --evidence "$DELIVERY_DIR/project-evidence.json" \
  --output "$DELIVERY_DIR/project-batch.json"
```

读取只在本项目库上以 query_only 执行，检查项目 ID、schema、登记摘要、账号与 BVID，
随后逐稿匿名 GET 并复用单稿原始字节验证。候选固定完整覆盖集合及其摘要。任一稿件
失败不输出残缺合计；任一稿件缺失的字段在整体中保持未知，明确的零参与求和。4 MiB
证据或 4096 稿件上限触发明确失败，需先由 Main 设计分段口径，不能静默截断集合。

prepare 离线重算每稿的原始响应、集合和合计，检查真实项目、来源、时区与指标映射。
snapshot 批次窗口起止相同，逐稿实际采集时间保留在证据，不能声称平台同时实时统计。
Main 确认后仍须核对实际页面。不同覆盖集合的快照不能相减声称当天增长；采集失败
保留宿主上次已确认事实。此处不新增 HTML 直读 SQLite 或宿主数据库写入权限。
