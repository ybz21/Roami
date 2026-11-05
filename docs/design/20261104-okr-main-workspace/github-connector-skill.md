# GitHub Connector Skill 的可复核原始证据

关联 [#679](https://github.com/ybz21/Roami/issues/679)，继续使用本目录的运行态和 Studio 方案。项目 Connector 以 Skill 为入口，Python 产出候选，Main 核验并使用已支持的项目确认操作。

## 产品设计与用户故事

数据成员继续原任务和原对话，读取项目内 Connector Skill 后一次取得同仓库两个指标。Main 需要事后复核实际原响应，不能只相信脚本成功、解析后字段或一个没有原字节可重算的 SHA。

同名仓库被重建时，已确认来源不能静默换成新的稳定 ID。失败保留旧事实，重复同日快照不算新增增长日；用户自定义脚本和现有内建 collect 的结果、时间与回执分开。

## 技术设计

- `parts/connectors/github/scripts/fetch_github.py` 继续使用标准库；可选 `--repository-id` 校验已确认身份，旧调用仍可进行未确认来源发现。已知稳定 ID 的工作流要求传入它。
- 候选保留 `evidence.payload`，另存 `evidence.http.status/headers/body`。body 是完整 UTF-8 响应文本，包含空白与换行；JSON 编解码后 UTF-8 字节和 SHA 不变。响应头仅包含公开时间、缓存和请求标识，不包含 Set-Cookie 或请求鉴权。
- 保持不重定向、响应大小边界、仓库名/ID与非负整数检查。非200、读取超时或身份不符均失败，不向 stdout 发出部分候选，不写项目数据或运行时。
- `references/evidence.md` 约束来源代码快照、日期和来源批次、项目根相对路径、Main 验收及兼容确认路径。`daily-loop.md` 补充当前轮完整读取 artifact 后走受管验收，以及不覆盖历史的记忆/索引维护。
- canonical `package.files` 同步包含新指引与代码。原生 Codex/Claude 与运行时轮子仍从同一正文打包；新增文件不等于旧生产 Python 已加载它。

当前 collect 会独立取一次来源，不是接收这个 Python 候选的批次发布接口。Main 必须记录两次请求的时间和证据，不能把第二次响应 SHA 说成第一次响应。通用 Skill 批次发布、项目绑定和 HTML 只读 SDK 保持独立的后续接通项。

## 验收记录

项目本地版本先完成8项原始字节、稳定来源、非法值、重定向和响应大小检查。随后由原 Main 续派同一数据成员的下一轮，实际匿名 HTTP200、原响应4842B，Main/Root分别重算原字节摘要一致；成员没有写确认数据。Main 经既有 collect 再取数，工作区 revision18→19，原任务受管验收成功，浏览器重新进入数据看板显示当日两项事实，未知指标仍缺测。两次请求间隔数分钟、计数相同，未记为增长或同一响应。

原 Main 随后维护当日日索引，明确素材批次、真实 producedAt、候选与确认时间；Root独立核对6条原件字节/SHA，旧产物没有移动。团队记忆以当前SHA追加，旧前缀逐字节相同且历史副本可恢复。记录在 `/tmp/okr-project-github-skill-20261106/`，私有工作区内容不上传公开截图。

canonical 的来源/CLI/打包/日更指引专项 **26项与6个子测试通过**，不访问公网或实际模型。最终 quick/full 与发布结果另行补录；当前不宣称已进入生产运行时。没有操作手机、发布新内容或启用 Main 日程。
