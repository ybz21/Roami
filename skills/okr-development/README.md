# OKR 初始化模板

**`assets/` 就是一整套项目初始化模板。整个复制，再根据对话填写、组合。**

```bash
okr_skill_dir=/path/to/skills/okr-development
okr_draft_dir="$(mktemp -d)"
cp -R "$okr_skill_dir/assets/." "$okr_draft_dir/"
```

`/.` 会把隐藏的 `.roami` 一起复制。已有项目先在草稿中合并，保留原项目的规则、
Main、团队、历史、数据和记忆。

```text
assets/                         # 复制后的项目根目录
├── AGENTS.md                    # 项目规则和团队记忆入口
├── README.md
└── .roami/okr/
    ├── AGENTS.md                # OKR 团队协作规则
    ├── README.md
    ├── okr.json                 # O、KR、指标、实施手段
    ├── dashboard.json           # 当前可用的看板组件和数据绑定
    ├── dashboard/               # 自定义 HTML 看板（须确认宿主支持）
    │   ├── index.html
    │   ├── style.css
    │   └── page.js
    ├── connectors/source/       # 采集 Skill 和来源绑定
    │   ├── SKILL.md
    │   └── connector.json
    ├── agents/                 # 项目 Main、职责和团队绑定
    │   ├── main.json
    │   ├── main.md
    │   ├── team.json
    │   └── swarm.json
    ├── skills/                 # 项目规划、取数协调、团队执行
    │   ├── okr-planning/SKILL.md
    │   ├── metric-collection/SKILL.md
    │   └── swarm-execution/SKILL.md
    ├── memory/                 # 团队记忆、重要事项、个人记忆
    │   ├── team.md
    │   ├── decisions.md
    │   └── members/
    ├── data/                   # 初始为空的事实、复盘记录
    │   ├── observations.jsonl
    │   └── reviews.jsonl
    ├── evidence/               # 实际采集和验收的证据
    ├── schedules/daily.json    # 默认关闭的日更提案
    └── state/                  # 保存后由宿主生成确认快照
```

复制后按[逐项编写说明](references/authoring.md)填写目标、日期、指标、来源、看板和职责。
需要 Python、MCP、其他图表或执行器时，从 `parts/` 复制相应部分组合；
`examples/` 是可选业务案例。项目 Main 和成员的真实实例、确认数据、有效调度由实际
注册和执行产生，初始化模板不预造这些结果。

自定义 HTML 先检查宿主 htmlDashboardSupported，再使用 parts/dashboard/html 清单和只读 SDK。
旧宿主继续使用 JSON 看板。通用 Connector Skill 执行与每日调度仍需对应适配器和实际注册回执，
当前内置取数和人工核验路径继续可用。
