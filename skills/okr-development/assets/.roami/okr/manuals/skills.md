# 项目 Skill 的编写、使用与改进

共同规则见项目根 AGENTS.md 第 6–7 节。

## 选入口与存放位置

| 工作 | 入口/位置 | 输出 |
| --- | --- | --- |
| O/KR 与看板定义 | `.roami/okr/skills/okr-planning/SKILL.md`、`manuals/dashboard.md` | 经过 save/sync 的定义与可用页面 |
| 收集与核对指标 | `.roami/okr/skills/metric-collection/SKILL.md` | 本轮候选与证据，交 Main 确认 |
| 具体来源取数 | `.roami/okr/connectors/<名称>/SKILL.md` | Python/MCP 原始响应、字段映射与批次候选 |
| 原团队执行 | `.roami/okr/skills/swarm-execution/SKILL.md` | 原成员当前轮次产物与独立验收 |
| 原 Main 定时唤醒 | `.roami/okr/skills/daily-operations/SKILL.md` | 调度/唤醒回执，执行仍由原团队完成 |

所有表内路径相对项目根；读取时用完整路径，不因 cwd 变化读成另一个项目的同名 Skill。Main 看 `agents/main.json` 和宿主确认的 `projectFiles.skills`；成员读取本轮实际指定的 Skill。原生执行器的全局 Skill 目录以本机安装和实际发现结果为准，不假定复制项目目录就完成全局安装。

看板运行文件在 `dashboard/`。重复页面生成可提炼成项目 `skills/dashboard-authoring/`，但这是按需新增的候选，不是当前模板已提供的能力；创建后还要按宿主支持的入口登记并验证读取。

## 编写一份项目 Skill

在隔离草稿准备 `<名称>/SKILL.md`，含 YAML 的 `name`、`description` 和正文：何时使用、读哪些确认输入、账号/权限边界、操作步骤、产物与独立验收、失败和未知结果如何恢复。路径标明相对哪一层。

需要确定性重复操作时添加 `scripts/`（Connector 以 Python 为主）；MCP 要写清当前可用工具、授权账号、参数及返回字段。来源口径放 `references/`，复用模板放 `assets/`。仅创建需要的文件，不把测试观测、凭据或编造回执放进初始化模板。

Connector 还要声明实际文件清单、source/metric 绑定和口径。先确认包，再执行其具体版本；包改动后重新确认，不能用旧绑定为新脚本背书。脚本只产候选，Main 复核后通过受管 record 发布；任何脚本不能直改运行时数据库、确认指针或观测历史。

## 从记忆到改进

1. 成员提出有本轮证据的经验或故障，写个人候选并在群聊交接。
2. Main 核对来源和当前结果，区分偶发现象与可复用方法，在团队记忆写结论、适用范围和未知。
3. 针对一个具体改进提出假设、预期指标、观察窗口与停止条件；编辑项目 Skill 候选，保留原版和变更理由。
4. 隔离验证脚本/模板及失败恢复，按宿主支持的确认流程发布；下一轮续派原成员，记录真正使用的路径、版本和结果。
5. 复盘保留/修改/回退；不要仅因一次调用成功把方法升级为全体强制规则。涉及账号发布、调度启用、权限或来源变更仍需对应授权。
6. 跨项目通用经验脱敏后回提仓库 `skills/okr-development`，通过测试、PR 和分发版本落地；各项目的定制先对比合并，不能整包覆盖。

定时执行必须调用真实已确认 Skill 并保留版本；保存 SKILL.md、添加名称、模型口头说“已学会”都不等于成功加载、执行或每日自动改进。
