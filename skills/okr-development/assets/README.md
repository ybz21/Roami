# {{projectName}}

{{objective}}

本目录是完整的项目骨架。先读 [AGENTS.md](AGENTS.md)，项目 Main 负责协调原有团队。

| 内容 | 位置 |
| --- | --- |
| OKR 团队规则 | [.roami/okr/AGENTS.md](.roami/okr/AGENTS.md) |
| 目标、KR、指标和实施手段 | [.roami/okr/okr.json](.roami/okr/okr.json) |
| 看板组件及绑定 | [.roami/okr/dashboard.json](.roami/okr/dashboard.json) |
| 自定义 HTML、样式和数据读取 | .roami/okr/dashboard/ |
| Connector Skill、脚本和来源绑定 | .roami/okr/connectors/ |
| 项目 Main、分工与团队绑定 | .roami/okr/agents/ |
| 规划、采集、执行工作流 | .roami/okr/skills/ |
| 团队记忆与重要事项 | .roami/okr/memory/ |
| 事实记录与证据 | .roami/okr/data/、.roami/okr/evidence/ |
| 每日采集提案 | [.roami/okr/schedules/daily.json](.roami/okr/schedules/daily.json) |
| 宿主生成的确认快照 | .roami/okr/state/ |

先填写项目名、目标、日期、指标、来源、看板和团队职责，再通过宿主支持的操作保存、
回读和验收。定义文件不是执行回执：自定义 HTML、Connector 和调度需确认宿主支持。
每日采集提案默认关闭；初始数据为空，未知值不补零。

真实产物在工作发生后保存到 YYYY/YYYYMM/YYYYMMDD/。修改已有项目时保留原 Main、
团队、规则、历史和 archive/artifacts 等旧目录，不用模板覆盖它们。
