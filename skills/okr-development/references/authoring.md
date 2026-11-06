# 逐项编写完整 OKR

## 先 CP，再组合

在新建或明确隔离的草稿目录执行，不能覆盖一个正在运行的项目：

```bash
okr_skill_dir=/path/to/skills/okr-development
okr_draft_dir="$(mktemp -d)"
cp -R "$okr_skill_dir/assets/." "$okr_draft_dir/"
mkdir -p "$okr_draft_dir/.roami/okr/connectors/github"
cp -R "$okr_skill_dir/parts/connectors/github/." \
  "$okr_draft_dir/.roami/okr/connectors/github/"
```

第二次复制前先创建目标目录。用 `/.` 复制隐藏目录。需要 MCP 就选 mcp 包，不需要
就不复制 Python。编辑已有项目时，这些步骤只在草稿执行；读取旧确认 revision 后合并
差异，保留其 Main、真实成员、来源历史、数据、记忆与用户其他规则。

## 每个部分怎么写

| 文件/目录 | 要写的内容 | 不能填什么 |
| --- | --- | --- |
| 项目 AGENTS.md | 指向 .roami/okr/AGENTS.md，团队/重要事项/个人记忆位置，产物目录 | 不替换已有项目规则 |
| .roami/okr/AGENTS.md | 团队协作、当轮产物、独立验收、消息来源与记忆约定 | 不把自述当验收，不绕过 unknown |
| okr.json | objective、日期、metrics、keyResults、initiatives、当前 revision、实际 swarm、autoCollect | 不塞观测、运行回执或虚构实例 |
| dashboard.json | schema1/widgets 或支持宿主上的 schema2/html 入口、资产与指标绑定 | 不把任意 HTML 写进现有 widget.type |
| dashboard/index.html | 用户自己的 HTML 布局；一指标一卡，组件绑定清晰 | 不读绝对路径、数据库、鉴权凭证 |
| dashboard/style.css | 现有主题/字号/间距令牌、响应式列与内部滚动 | 不改变主应用壳或污染父页面 |
| dashboard/page.js | 只读 okr.data.read/subscribe、格式化、ECharts/表格渲染、离开清理 | 不派工、不写数据、不自行调用 Roami 管理 API |
| connectors/<name>/SKILL.md | 来源、口径、账号、指标映射、采集步骤、校验、证据和失败处理 | 不宣称一个文件就是启用状态 |
| connectors/<name>/scripts/ | 真实 Python 取数/标准化；输出候选事实与原始证据 | 不写 JSONL/current.json/runtime SQLite |
| connectors/<name>/references/ | MCP 工具/effect/schema、账号与字段映射，必要来源说明 | 不猜连接名、不携带凭证 |
| connectors/<name>/connector.json | 当前支持的来源绑定；未来 Skill schema 需兼容迁移 | 不执行任意 command 字段 |
| agents/main.json / main.md | 项目 Main 的指引和已支持技能列表；职责是协调、指挥与核验 | 不写首页 Main 或另造 conversation ID |
| agents/team.json | schema1、稳定角色 id、名称、executor、职责；空 roles 也合法 | 不把期望职责当真实成员/实例 |
| agents/swarm.json | 受管团队登记后取得的真实绑定；未建团队先为空 | 不复制其他项目团队 ID |
| skills/ | 项目规划、采集协调、执行等工作流；Connector 包单独在 connectors/ | 不把一轮任务写成新职责/新实例 |
| skills/daily-operations/ | 外部日程唤醒脚本与开工/复盘提示；填真实项目/Main、IANA时区和语义时段，先dry-run | 不让Main自己运行，不把accepted当执行，不从旧运行时回退send |
| memory/team.md | 有来源的团队事实、约定与工作知识 | 不当执行日志或成功证明 |
| memory/decisions.md | 日期、来源、决定、负责人、当前状态/未决事项 | 不静默覆盖旧决定 |
| memory/members/ | 取得真实 stable-member-id 后写个人笔记 | 不按 r2/r3 另建记忆 |
| schedules/daily.json | 默认关闭提案，确认 Skill、时刻与 IANA 时区后再注册 | 不虚构 nextDue、不能用提醒冒充执行 |
| data/observations.jsonl / reviews.jsonl | 新草稿为空；事实由受管操作发布并导出 | 不放演示数字、不替换旧历史 |
| evidence/ | 实际来源/验收证据，保留原文件与哈希 | 不用空占位证据声称完成 |
| state/ | 宿主生成 immutable snapshots 与 current.json | 模板不生成确认指针 |
| YYYY/YYYYMM/YYYYMMDD/ | 真正发生工作后按方法/task/revision/run 记录产物与索引 | 不预造完成目录或把旧文件移成当天成果 |

## 目标、指标与手段

指标 ID 稳定，名称、单位、来源和日期口径明确。当前来源只支持 manual 或 github；
GitHub 还需要 repo=owner/repo、field=stars/forks。sourceKey 是宿主派生字段，不填入保存配置。
KR 的 metricId 必须存在，horizon 是 long/short，mode 是 increase/atLeast/atMost，target
是确认后的数值，dueDate 在项目日期内。目标值不能沿用示例数字当作用户确认。
实施手段写 title/channel/keyResultIds/description/acceptance；KR 与方法数量按目标决定。
未知基线不在配置中补零；没有观测则显示未知。

## 组合看板

JSON 兼容路径：从 metricTrend/keyResults/nextAction 中选择注册组件，数据页只展示数据。
HTML 路径：复制 parts/dashboard 的片段到 index.html，填 metricId/名称，按实际组件
选择 parts/dashboard/html/dashboard.json 覆盖，并按实际组件编写渲染；完整模板 page.js 支持数字与趋势/柱图，图表在 okr.ready() 后使用宿主 ECharts。
先确认 projectFiles.htmlDashboardSupported；不支持时保留 HTML 草稿，不改为直接获取生产凭证。

## 组合来源与职责

复制 Python 或 MCP Skill 包到 connectors/<name>/；目录名与 frontmatter.name 保持一致。
明确同一请求是否给多个指标供数，不为每张卡重复执行同一来源请求。当前集成需使用
宿主支持的 builtin/manual 操作；新 Skill 发现、批量提交与日更等待真实协议接通。

角色片段填 id/name/executor/duty，合入 agents/team.json。已有项目保留稳定角色及
真实成员映射；新职责是计划，只有 register/plan 的真实回执才能证明登记/派工。

## 保存与验证

README 的 projectName 与所有配置中的 {{...}} 是有意的模板参数，必须全部替换。target 等数值字段要改成数值，
日期用 YYYY-MM-DD。读取当前 project_okr_context；save 的 payload 需要把 dashboard.json
和 agents/team.json 组合为 dashboard/team 字段，并使用真实当前 revision。CLI 参数以
已安装 roami project okr help 为准。首次 save 后宿主生成 builtin 参考与确认快照；以后
编辑受支持定义可 sync，冲突先读新版本并保留草稿。

回读发布的 workspace、文件及 UI，核对 source/date/units、指针 revision、期望团队和
真实登记的区别。一个复制成功的目录不是已启用 HTML、已采集数据或每日执行的证明。
