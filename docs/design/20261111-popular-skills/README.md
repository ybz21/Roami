# 热门技能与本机 Agent 安装

## 产品设计

能力中心的「市场」默认展示所选 skills.sh 来源的热门技能，沿用上游累计安装量榜单顺序。
卡片展示技能名称、仓库和安装量，点击进入内容预览。搜索仍由显式提交触发，搜索后可返回热门榜。
不展示虚构的热度或维护一份静态推荐清单；上游不可用时展示可重试错误。

技能详情沿用桌面弹窗和手机全屏二级页。说明按需展开，安装位置默认全选，可取消部分位置。
「本机」指当前所选 Roami 节点，不是查看页面的手机。

## 用户故事

- 没有明确关键词时，打开市场即可浏览热门技能。
- 查看技能的完整说明、来源与附带文件后，一次安装到所有 Roami 支持的 Agent。
- 只需要某个 Agent 时，保留所需安装位置。
- 安装冲突或失败后，保留原有技能、预览及安装选择，按提示修复后重试。

## 技术设计

- `market_catalogs.py`：skills.sh 空查询读取首页结构化 `initialSkills` 数据，保留前二十项中的仓库型技能和累计安装数。解析脚本数据，不执行上游脚本；响应限制为 2 MB。
- `CapabilityMarkets.search`：仅 skills.sh 允许空查询；沿用既有权限、并发合并和 60 秒缓存，不增加轮询。
- `CapabilityMarket.tsx`：进入或切换技能市场时加载热门榜；预览使用既有 `preview` 与 `prepare`，安装提交十分钟有效的固定内容回执。
- `MarketInstallations.install`：兼容原有调用；新增可选 `targets` 仅用于技能。
- `skill_agent_installation.py`：通过现有校验后的技能包生成不可变本机副本，并发布到选定的发现目录。失败时回收本次新建的链接，保留之前已存在的安装；同内容重试幂等，同名不同内容拒绝覆盖。
- `skill_package.materialize_package(force=True)`：即便技能没有附带文件，也保留完整 `SKILL.md` 包。

| 位置 | 目录 / 行为 |
| --- | --- |
| 本机（Codex、Pi 等） | `~/.agents/skills/<name>` |
| Claude Code | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills/<name>` |
| OpenCode | `${XDG_CONFIG_HOME:-~/.config}/opencode/skills/<name>` |
| Roami | 当前节点的持久能力注册与完整技能包 |

目录依据 [skills CLI Agent 配置](https://github.com/vercel-labs/skills/blob/main/src/agents.ts)。
上述目录保存指向节点不可变包的符号链接。仅发布技能文件，不执行技能脚本或安装 Agent 软件。
新 Agent 会话读取已安装内容；运行中的会话可能需要重开。

## 验收

实现与验收记录见 [acceptance.md](acceptance.md)。截图为临时验收产物，不提交到主分支。
