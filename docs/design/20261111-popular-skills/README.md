# 热门技能与本机 Agent 安装

## 产品设计

能力中心的「市场」默认展示所选 skills.sh 来源的热门技能，提供累计、24 小时趋势、实时热门三种榜单，沿用上游排序。
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

- `skills_sh_api.py`：统一适配 skills.sh JSON 榜单、搜索与正式 API 文件快照，不再解析页面或依赖 React 输出。公开榜单保留整页仓库型结果并正确翻页，不跳过页内条目。
- `market_catalogs.py`：GitHub raw 文件下载失败时使用固定树中的 blob API；REST 限流 / 暂时不可用时回退到同一 commit 的归档，继续保留脚本、引用与许可证。已知 commit 时不重新解析 HEAD。
- `CapabilityMarkets.search`：仅 skills.sh 允许空查询；缓存键包含榜单类型，沿用既有权限、并发合并和 60 秒缓存，不增加轮询。
- `CapabilityMarket.tsx`：进入或切换技能市场时加载热门榜；一次 `preview` 返回完整内容和十分钟有效的安装回执；CLI 的 `prepare` 继续返回摘要。安装提交固定内容回执，不再次抓取内容。
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

## skills.sh API 接入（2026-11-11 修订）

[官方 API 文档](https://skills.sh/docs/api)提供以下接口：

| 功能 | 正式 API |
| --- | --- |
| 三种榜单 | `/api/v1/skills?view=all-time|trending|hot&page=0&per_page=20` |
| 搜索 | `/api/v1/skills/search?q=...&limit=20` |
| 完整内容 | `/api/v1/skills/{owner}/{repo}/{skill}` |

正式 API 需要 Vercel OIDC，匿名请求实测为 401。服务端存在 `VERCEL_OIDC_TOKEN` 时启用正式 API；每次请求读取最新值，只向官方 skills.sh 域名发送，不传给自定义镜像或浏览器。令牌刷新由部署环境负责，文档说明其有效期约十二小时。授权过期返回市场错误，不把上游 401 传播为 Roami 登录失效。

没有 OIDC 时使用网站自身的公开 JSON 接口：`/api/skills/{view}/{page}` 和 `/api/search?q=...&limit=20`。前者是网站实际使用的接口，区别于需要授权的正式 v1 API。此时技能内容通过 GitHub 固定提交下载。

正式详情 API 的 `files` 快照包含完整 `SKILL.md` 和支持文件，以内容摘要固定安装版本；无快照时继续使用 GitHub 下载。内容始终经过现有路径、数量和大小校验。
