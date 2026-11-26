# Roami 产品演进证据索引

本文支撑[一页讲稿](README.md)，在“六阶段概述”和[全量提交采集](commits.md)之间提供可回查的细化证据：分阶段功能节点、功能域演进、版本标签、当前代码落点与叙事边界。

## 1. 统计口径

- 基线：`eb1f9df15270eea61992e77dfaef4ab54964b471`，作者日期 2026-11-26。
- 起点：`e5ab22fbd606b77deddcdc41a61bce89bf785101`，作者日期 2026-05-27。
- `git rev-list --count eb1f9df1` 为 **1208**，包含合并提交；文档采集自身的新提交不计入该基线。
- 阶段表和全量 Markdown 按**作者日期**（`%aI`）排序；CSV 同时保留作者日期与提交者日期（`%cI`）。作者日期表示实现节点，不等同于合入或对外发布日期。
- “首发”表示本基线中能找到的首次重要实现；“增强”表示已有能力的扩展；“收口”表示安装、统一入口、可靠性或版本整理。它们是叙事分类，不是 Git 原生属性。
- 历史提交正文中的测试数量、真机验收和截图说明只作为**当时的提交记录**引用，本次没有重放这些历史验收。
- 版本节点按本地标签、标签说明及标签指向提交核对：`v0.1.0-rc.1`、`v0.1.0-rc.2`、`v0.2.0-rc.1`、`v0.2.0-rc.2`、`v0.2.1`。

### 提交活动分布

下表从全量 CSV 的主题解析 `feat` / `fix`；“其他”包含 docs、refactor、test、perf、合并提交及非 Conventional Commit 主题等。scope 只统计能按 Conventional Commit 解析的记录，用作观察开发重心的线索，不代表完整功能分类。

| 月份 | 全部 | feat | fix | 其他 | 高频 scope 示例 |
|---|---:|---:|---:|---:|---|
| 2026-05 | 10 | 7 | 1 | 2 | 早期提交未使用 scope |
| 2026-06 | 166 | 26 | 22 | 118 | mobile 8、web 5、swarm 4 |
| 2026-07 | 296 | 78 | 80 | 138 | project 24、web 22、p2p 18、worktree 13 |
| 2026-08 | 96 | 46 | 35 | 15 | web 42、chat 6、cluster 5 |
| 2026-09 | 46 | 20 | 19 | 7 | shell 6、p2p 4、workspace 3 |
| 2026-10 | 227 | 44 | 168 | 15 | agent 78、rsi 41、mobile 17 |
| 2026-11 | 367 | 91 | 239 | 37 | okr 109、agent 63、models 42、swarm 19 |
| **合计** | **1208** | **312** | **564** | **332** | — |

提交数和 fix 数只说明开发活动，不能直接推断用户价值、质量或稳定性。

## 2. 全量提交采集

- [全量提交时间线](commits.md)：按月分组，逐一列出全部 **1208** 个提交的日期、短哈希、类型、主题和标签。
- [结构化明细 CSV](commits.csv)：UTF-8 BOM 编码，包含序号、完整哈希、短哈希、父提交、作者与提交者、双时间戳、合并标记、标签、PR 号、Conventional Commit 类型／范围／破坏性标记、主题和正文。
- 范围是基线 `eb1f9df1` 的全部可达提交，包含 **127** 个合并提交；不包含其他未合入分支，也不包含本次文档采集自身的新提交。
- `pr_number` 仅从 `Merge pull request #N` 和主题末尾 `(#N)` 两种常见格式提取；空值表示未从主题识别，不等于一定没有 PR。
- `type`、`scope`、`breaking` 由主题和正文中的约定标记解析；空值通常表示早期或非规范主题，不应人工补猜。
- 采集后与 `git rev-list eb1f9df1` 的完整哈希集合比对，1208 条全部匹配，无遗漏、无重复；CSV 再解析仍为 1208 条。

## 3. 分阶段详细证据

### 阶段一｜5 月：tmux 封装之上，直接形成 AI 原生编排

| 日期 | 性质 | 功能与变化 | 提交依据 |
|---|---|---|---|
| 05-27 | 首发 | 友好 tmux 封装，降低会话创建与操作门槛 | [`e5ab22fb`](https://github.com/ybz21/Roami/commit/e5ab22fb) |
| 05-27 | 首发 | `spawn / group / status / wait / capture / collect` 组成并行任务原语；输出落日志，支持 `--json`，附 Claude Code Skill 与安装器 | [`1dd3c97d`](https://github.com/ybz21/Roami/commit/1dd3c97d) |
| 05-27 | 扩展 | 无参数进入交互 TUI；加入多智能体编排和全局环境变量管理 | [`00adf8aa`](https://github.com/ybz21/Roami/commit/00adf8aa)、[`ccfd7ff2`](https://github.com/ybz21/Roami/commit/ccfd7ff2)、[`aaf72b00`](https://github.com/ybz21/Roami/commit/aaf72b00) |
| 05-27 | 验证与整理 | 增加 Agent 端到端测试，按真实测试修订 Skill；Skill 调整为目录形式 | [`aaddd15f`](https://github.com/ybz21/Roami/commit/aaddd15f)、[`efdf9ab9`](https://github.com/ybz21/Roami/commit/efdf9ab9)、[`50e7d937`](https://github.com/ybz21/Roami/commit/50e7d937) |
| 05-30 | 扩展 | father skill 引入 Claude Code 多实例监护 | [`e8324522`](https://github.com/ybz21/Roami/commit/e8324522) |

**阶段判断：** 起点已经不只是“更好用的 tmux”。并行派活、等待、采集和机器可读输出在同一天出现，确定了 AI 操控多会话的基本方向。

### 阶段二｜6 月：Web 控制台、真实工具镜像与 Roam 品牌

| 日期 | 性质 | 功能与变化 | 提交依据 |
|---|---|---|---|
| 06-15 | 首发 | 新增 Go 后端 + Vite/TypeScript 前端，包含认证、PTY、流式传输与服务端骨架 | [`e14919ec`](https://github.com/ybz21/Roami/commit/e14919ec) |
| 06-15 至 06-17 | 首发 | 蜂群编排进入 CLI 和 Web：成员完成标记、依赖解锁、看板／广场、Claude/Codex 成员及 master/worker 角色 | [`82d28180`](https://github.com/ybz21/Roami/commit/82d28180)、[`0b0a6b3a`](https://github.com/ybz21/Roami/commit/0b0a6b3a)、[`b02ca3da`](https://github.com/ybz21/Roami/commit/b02ca3da)、[`0466e470`](https://github.com/ybz21/Roami/commit/0466e470) |
| 06-16 至 06-17 | 首发 | 通过 CDP screencast 镜像真实 Chrome，支持多标签，并接入原生 DevTools 调试入口 | [`142c925e`](https://github.com/ybz21/Roami/commit/142c925e)、[`73575613`](https://github.com/ybz21/Roami/commit/73575613) |
| 06-17 | 品牌 | 首次启用 **Roam** 品牌与 “Code anywhere, anytime” 定位 | [`1bb121ef`](https://github.com/ybz21/Roami/commit/1bb121ef) |
| 06-18 至 06-25 | 扩展 | 对话页、文件上传下载、粘贴图片、Shift+Enter 换行和服务端跨设备偏好逐步形成 | [`78f92edb`](https://github.com/ybz21/Roami/commit/78f92edb)、[`680da63e`](https://github.com/ybz21/Roami/commit/680da63e)、[`20969cfe`](https://github.com/ybz21/Roami/commit/20969cfe) |
| 06-19 至 06-22 | 收口 | 统一 Hash 路由、主题与全站蓝色视觉，建立 i18n 体系并增强文件管理 | [`05f9d68e`](https://github.com/ybz21/Roami/commit/05f9d68e)、[`a9a6e30d`](https://github.com/ybz21/Roami/commit/a9a6e30d) |
| 06-23 | 架构 | ttmux CLI 完成原生 Go 重写，随后移除废弃 Bash 桥 | [`44d8c598`](https://github.com/ybz21/Roami/commit/44d8c598)、[`09a65e73`](https://github.com/ybz21/Roami/commit/09a65e73) |
| 06-24 至 06-27 | 首发 | 语音输入、豆包／火山 ASR 与 OpenAI 兼容识别接入；自签 CA、叶子证书和证书下载完善手机安全上下文 | [`7a24b670`](https://github.com/ybz21/Roami/commit/7a24b670)、[`58150dc9`](https://github.com/ybz21/Roami/commit/58150dc9)、[`9ca808b9`](https://github.com/ybz21/Roami/commit/9ca808b9) |
| 06-25 至 06-26 | 手机 | PWA 图标、软键盘避让和移动布局开始系统适配 | [`56d10efa`](https://github.com/ybz21/Roami/commit/56d10efa) |
| 06-27 至 06-29 | 首发 | “手机”标签加入 Android/iOS 镜像与控制、平台开关、按需依赖安装和连接配置 | [`77d04d36`](https://github.com/ybz21/Roami/commit/77d04d36)、[`9230e933`](https://github.com/ybz21/Roami/commit/9230e933)、[`286d3918`](https://github.com/ybz21/Roami/commit/286d3918) |

**阶段判断：** 管理面从本机 CLI 扩展到浏览器，操作对象也从 Agent 终端扩展到真实 Chrome 和手机。iOS 适配在当前功能清单中仍列为实验性能力，不能按首发提交推断为全环境成熟支持。

### 阶段三｜7 月：项目、Worktree、插件与交付流程

| 日期 | 性质 | 功能与变化 | 提交依据 |
|---|---|---|---|
| 07-01 | 首发 | 文件浏览接入 Monaco；统一 `FileWorkspace`，支持平铺／VSCode 树、双栏编辑、外部变更重载和 Markdown 预览 | [`d4f2af11`](https://github.com/ybz21/Roami/commit/d4f2af11)、[`9344d8a2`](https://github.com/ybz21/Roami/commit/9344d8a2)、[`611cd6dd`](https://github.com/ybz21/Roami/commit/611cd6dd) |
| 07-03 至 07-04 | 首发 | 新建会话支持 Git worktree；Markdown 预览增加 Mermaid | [`42388b79`](https://github.com/ybz21/Roami/commit/42388b79)、[`6d408f56`](https://github.com/ybz21/Roami/commit/6d408f56) |
| 07-07 | 首发 | 插件系统 v1 包含 manifest、权限、审计、JSON-RPC 宿主、SDK、plugind、CLI 和 Web 面板；Review Mesh 与飞书桥作为内置扩展进入 | [`7b97e1e5`](https://github.com/ybz21/Roami/commit/7b97e1e5)、[`f4f7249f`](https://github.com/ybz21/Roami/commit/f4f7249f) |
| 07-07 | 扩展 | 飞书常驻管家把消息接入主 Agent，并将复杂工作委派给 worker | [`2ac968e8`](https://github.com/ybz21/Roami/commit/2ac968e8) |
| 07-09 | 安装与发行 | 配置迁移到 `config.yaml`，补首次口令与数据目录迁移，打包单一自包含二进制；同日形成两个 `v0.1.0` RC 标签 | [`d1a0eaa1`](https://github.com/ybz21/Roami/commit/d1a0eaa1)、[`v0.1.0-rc.1`](https://github.com/ybz21/Roami/releases/tag/v0.1.0-rc.1)、[`v0.1.0-rc.2`](https://github.com/ybz21/Roami/releases/tag/v0.1.0-rc.2) |
| 07-12 至 07-13 | 首发 | `fork / children / parent / ls --tree` 形成子会话原语；自然语言优先派活、worktree 领域服务、管理和收尾界面、多 Agent 同题竞赛落地 | [`1c4c83b4`](https://github.com/ybz21/Roami/commit/1c4c83b4)、[`523eb780`](https://github.com/ybz21/Roami/commit/523eb780)、[`765c3202`](https://github.com/ybz21/Roami/commit/765c3202)、[`20097768`](https://github.com/ybz21/Roami/commit/20097768) |
| 07-14 至 07-15 | 产品转折 | 项目先以仓库聚合任务，再升为一等存储对象；导航移除独立“会话”和“蜂群”入口，项目成为组织工作的主入口 | [`1c751d5f`](https://github.com/ybz21/Roami/commit/1c751d5f)、[`03619ab1`](https://github.com/ybz21/Roami/commit/03619ab1)、[`0e33914f`](https://github.com/ybz21/Roami/commit/0e33914f)、[`8a280ad3`](https://github.com/ybz21/Roami/commit/8a280ad3) |
| 07-14 | 扩展 | 主机监控插件提供 CPU、GPU、内存、磁盘和网络仪表盘 | [`768bb81a`](https://github.com/ybz21/Roami/commit/768bb81a) |
| 07-15 至 07-17 | 交付状态 | 补合入检测、待输入状态，以及已提交／已推送／已合入的分阶段状态；手机文件与插件详情改全屏二级页 | [`f0a46e07`](https://github.com/ybz21/Roami/commit/f0a46e07)、[`9315fd00`](https://github.com/ybz21/Roami/commit/9315fd00)、[`567de12e`](https://github.com/ybz21/Roami/commit/567de12e)、[`6a0df17b`](https://github.com/ybz21/Roami/commit/6a0df17b) |
| 07-17 | 主动工作 | Cron 插件和可视化编辑器支持定时调用 Agent 或执行命令 | [`a5ac761f`](https://github.com/ybz21/Roami/commit/a5ac761f)、[`e086ea24`](https://github.com/ybz21/Roami/commit/e086ea24) |
| 07-17 | 多机底座 | 首版集群后端实现两种模式、yamux 隧道、Broker 反代、节点注册、心跳与端到端测试；当时前端切换器仍是后续增量 | [`8286ae1a`](https://github.com/ybz21/Roami/commit/8286ae1a) |
| 07-20 至 07-21 | 传输 | WebRTC/P2P 从后端文件分块传输扩到前端下载、状态、STUN 配置和镜像 DataChannel，并保留 HTTP/FRP 回退 | [`0b583ad9`](https://github.com/ybz21/Roami/commit/0b583ad9)、[`e3a2f679`](https://github.com/ybz21/Roami/commit/e3a2f679)、[`20aadccc`](https://github.com/ybz21/Roami/commit/20aadccc)、[`aa518e5c`](https://github.com/ybz21/Roami/commit/aa518e5c) |
| 07-28 至 07-29 | 架构收口 | 项目、会话和记录获得稳定 ID；tmux 内部会话名改用不可变 ID；Git 面板补提交树、分支和 worktree 分叉图 | [`a906030b`](https://github.com/ybz21/Roami/commit/a906030b)、[`5c924e37`](https://github.com/ybz21/Roami/commit/5c924e37)、[`8931f54c`](https://github.com/ybz21/Roami/commit/8931f54c) |

**阶段判断：** 7 月的关键不是单个编辑器或 Git 面板，而是把“需求输入 → 隔离工作区 → 并行执行 → 对比 → 合并／收尾”组织成项目交付链。多机与 P2P 此时先落底座，不能写成当月已经具备完整多端体验。

### 阶段四｜8—9 月：统一工作台、持久性与 Roami 更名

| 日期 | 性质 | 功能与变化 | 提交依据 |
|---|---|---|---|
| 08-03 至 08-05 | 交互收口 | 桌面／移动响应式重做，Git/Worktree 进入工作台分栏；全局搜索覆盖项目、会话、文件、插件和蜂群；对话密度与工具卡片统一 | [`a437e7af`](https://github.com/ybz21/Roami/commit/a437e7af)、[`171bf2f9`](https://github.com/ybz21/Roami/commit/171bf2f9)、[`97656b2e`](https://github.com/ybz21/Roami/commit/97656b2e)、[`5256498b`](https://github.com/ybz21/Roami/commit/5256498b) |
| 08-07 至 08-08 | 交互收口 | 输入卡、侧栏轨道、可调分栏与右侧抽屉统一；概览并入项目工作台 | [`f7dfe7aa`](https://github.com/ybz21/Roami/commit/f7dfe7aa)、[`f6a51e1f`](https://github.com/ybz21/Roami/commit/f6a51e1f)、[`4c262441`](https://github.com/ybz21/Roami/commit/4c262441) |
| 08-10 至 08-11 | 多机成形 | 中心／节点数据面接入前端；设置页重构，终端标签按机器保存；手机可切机器，中心状态与异常进入页面 | [`9bdd7803`](https://github.com/ybz21/Roami/commit/9bdd7803)、[`4972260d`](https://github.com/ybz21/Roami/commit/4972260d)、[`ef143890`](https://github.com/ybz21/Roami/commit/ef143890) |
| 08-12 | 数据底座 | 项目、竞赛、会话目录和蜂群台账收敛到 `meta.db`；统一开库、WAL、事务迁移和备份，保留重启后的项目与会话历史 | [`86341d01`](https://github.com/ybz21/Roami/commit/86341d01) |
| 08-12 至 08-14 | 设备与历史 | 已结束会话可见并可重开；多 Android 设备可切换；redroid 下线，AVD 支持创建与启停；文件面板支持音视频播放 | [`4db7dd9e`](https://github.com/ybz21/Roami/commit/4db7dd9e)、[`1a7f8b8d`](https://github.com/ybz21/Roami/commit/1a7f8b8d)、[`f1583f89`](https://github.com/ybz21/Roami/commit/f1583f89)、[`7ba02b86`](https://github.com/ybz21/Roami/commit/7ba02b86) |
| 08-23 至 08-24 | 可靠性 | 会话级内存护栏、会话懒恢复、Codex 对话恢复和机器级 L2 总量闸落地 | [`e0a536a4`](https://github.com/ybz21/Roami/commit/e0a536a4)、[`875f21aa`](https://github.com/ybz21/Roami/commit/875f21aa)、[`27adc81d`](https://github.com/ybz21/Roami/commit/27adc81d) |
| 08-26 至 08-30 | 扩展 | 底部状态条支持插件贡献；会话间拖放可建立沟通指引；主机监控补 swap 管理 | [`da0b3ea9`](https://github.com/ybz21/Roami/commit/da0b3ea9)、[`aeea46f2`](https://github.com/ybz21/Roami/commit/aeea46f2)、[`42bd0db9`](https://github.com/ybz21/Roami/commit/42bd0db9) |
| 09-04 | 工作台转折 | 项目／任务／会话树、全局标签、跟随当前 worktree 的右栏形成统一工作区；服务重启保留 tmux，休眠会话按原目录和对话恢复 | [`2c8bc548`](https://github.com/ybz21/Roami/commit/2c8bc548) |
| 09-07 | 主动工作与自检 | Cron 增加执行记录、通知和产物；自检清单与自动脚本落地；内存 L2 在制动前先尝试 zram | [`5f52b942`](https://github.com/ybz21/Roami/commit/5f52b942)、[`dce4bc95`](https://github.com/ybz21/Roami/commit/dce4bc95)、[`f5d23b4a`](https://github.com/ybz21/Roami/commit/f5d23b4a) |
| 09-07 | 命令与品牌 | `roam` 短暂统一命令入口后，当天完成 **Roam → Roami**：二进制、数据目录和环境变量迁移，同时保留旧命令软链与兼容别名 | [`40294bd6`](https://github.com/ybz21/Roami/commit/40294bd6)、[`1e2a00d3`](https://github.com/ybz21/Roami/commit/1e2a00d3) |
| 09-08 | 发行 | `v0.2.0-rc.1` 标签说明收口统一 CLI、任务工作区、Cron 结果、自检、语音与内存治理等能力 | [`v0.2.0-rc.1`](https://github.com/ybz21/Roami/releases/tag/v0.2.0-rc.1) |
| 09-10 至 09-11 | P2P 增强 | STUN 多服务器、实测与优选、P2P 状态进入底部状态条；图片、视频和 PDF 也可经 Service Worker 走直连 | [`d449ac10`](https://github.com/ybz21/Roami/commit/d449ac10)、[`5428b3de`](https://github.com/ybz21/Roami/commit/5428b3de)、[`fc7033e0`](https://github.com/ybz21/Roami/commit/fc7033e0) |
| 09-14 至 09-22 | 连续性 | 右栏状态、文件树展开状态、文件标签和阅读位置可恢复；语音交互改为显式启停；Keepalive 插件按会话屏幕状态催办 | [`06f777d7`](https://github.com/ybz21/Roami/commit/06f777d7)、[`489ecc9c`](https://github.com/ybz21/Roami/commit/489ecc9c)、[`dadb7589`](https://github.com/ybz21/Roami/commit/dadb7589)、[`54fa345f`](https://github.com/ybz21/Roami/commit/54fa345f) |

**阶段判断：** 这一阶段把“功能能用”推进到“工作能持续”：统一身份、统一存储、可恢复会话、可恢复界面和多机入口共同支撑长期使用。Roami 是 9 月更名；Roam 品牌实际在 6 月 17 日已经出现。

### 阶段五｜10 月：内置助手、能力中心与 Android 原生客户端

| 日期 | 性质 | 功能与变化 | 提交依据 |
|---|---|---|---|
| 10-08 至 10-09 | Agent 扩展 | 10 月 8 日先在会话中展示 OpenCode／Pi 标识；10 月 9 日统一注册并提供本机发现与额度插件。两者不是同一天的同一项实现 | [`2868d854`](https://github.com/ybz21/Roami/commit/2868d854)、[`3c187dfe`](https://github.com/ybz21/Roami/commit/3c187dfe) |
| 10-09 至 10-11 | 原生客户端 | 手机版首页、会话与 Android App 落地；随后补宽版状态小组件、会话项目归属和手机会话头 | [`a5098491`](https://github.com/ybz21/Roami/commit/a5098491)、[`1ff718c6`](https://github.com/ybz21/Roami/commit/1ff718c6)、[`e96fe91e`](https://github.com/ybz21/Roami/commit/e96fe91e) |
| 10-09 至 10-13 | 工作台与观测 | 侧栏页面纳入统一标签；补插件守护恢复、项目会话活动和 AI 足迹／对话任务统计 | [`fd485b2d`](https://github.com/ybz21/Roami/commit/fd485b2d)、[`24d71456`](https://github.com/ybz21/Roami/commit/24d71456)、[`c31a2739`](https://github.com/ybz21/Roami/commit/c31a2739) |
| 10-17 | 架构收口 | 统一 Roami 命令入口、核心架构与数据库布局 | [`a27f13a4`](https://github.com/ybz21/Roami/commit/a27f13a4) |
| 10-19 | 产品转折 | 接入 Python 主智能体运行时和 Go 统一入口：主对话派活、执行消息、能力目录、统一记忆、模型／思考强度、输入队列和 CLI 回报通道 | [`957a9599`](https://github.com/ybz21/Roami/commit/957a9599) |
| 10-19 至 10-21 | 工作闭环 | 首页整合任务、消息、记忆和可预览产物；任务内可查看、干预子智能体，主会话界面随之精简 | [`eb9332cd`](https://github.com/ybz21/Roami/commit/eb9332cd)、[`74527ce0`](https://github.com/ybz21/Roami/commit/74527ce0)、[`4032a2f7`](https://github.com/ybz21/Roami/commit/4032a2f7) |
| 10-21 | 能力平台 | 能力中心统一管理 Skill、MCP、CLI 等，并将专业 Agent 纳入同一入口 | [`4cb2e27d`](https://github.com/ybz21/Roami/commit/4cb2e27d) |
| 10-22 | 专业会话与模型 | 受管 native 会话持久化并打通任务／项目；专业 Agent 支持升级、模型服务预设和服务商模型选择 | [`b0807c8e`](https://github.com/ybz21/Roami/commit/b0807c8e)、[`a5367dfc`](https://github.com/ybz21/Roami/commit/a5367dfc)、[`36bbac3f`](https://github.com/ybz21/Roami/commit/36bbac3f) |
| 10-23 | 记忆与市场 | 记忆浏览重做并归并重复偏好；能力市场接入开放来源，统一 MCP 与专业任务调用；形成 `v0.2.0-rc.2` | [`9baf4764`](https://github.com/ybz21/Roami/commit/9baf4764)、[`dc44c96f`](https://github.com/ybz21/Roami/commit/dc44c96f)、[`v0.2.0-rc.2`](https://github.com/ybz21/Roami/releases/tag/v0.2.0-rc.2) |
| 10-24 至 10-29 | RSI 实验 | 开发版增加按次运行、节点产物、本地问题复测与 GitHub 汇总；后续补工作流视图和运行限额。提交明确保留失败、阻塞与未知计量，诊断不自动晋级 | [`33768eac`](https://github.com/ybz21/Roami/commit/33768eac)、[`af62d7d0`](https://github.com/ybz21/Roami/commit/af62d7d0) |
| 10-26 至 10-29 | 模型底座 | 本地模型代理、限额、用量统计、按上游费用计费和模型单价管理逐步形成；`v0.2.1` 优化首屏资源 | [`f3622829`](https://github.com/ybz21/Roami/commit/f3622829)、[`7342f3ae`](https://github.com/ybz21/Roami/commit/7342f3ae)、[`bc76414b`](https://github.com/ybz21/Roami/commit/bc76414b)、[`v0.2.1`](https://github.com/ybz21/Roami/releases/tag/v0.2.1) |
| 10-29 至 10-31 | 执行可视化与 Skill | 对话实时展示工具与派生执行；演示文稿结构读取、PPTX 编辑、视频拼接和数值概况等外挂 Skill 扩充非编程任务能力 | [`e383b06c`](https://github.com/ybz21/Roami/commit/e383b06c)、[`dda200df`](https://github.com/ybz21/Roami/commit/dda200df)、[`ecc89132`](https://github.com/ybz21/Roami/commit/ecc89132)、[`504c2ec6`](https://github.com/ybz21/Roami/commit/504c2ec6) |

**阶段判断：** 10 月出现两条并行升级：客户端从移动 Web 扩到原生 Android；服务端从“承载专业 Agent”扩到“自身具备对话、任务、记忆、工具和能力管理”。RSI 此时是实验与评测基础，不是完整自进化闭环。

### 阶段六｜11 月：OKR、长期团队与模型编排

| 日期 | 性质 | 功能与变化 | 提交依据 |
|---|---|---|---|
| 11-01 至 11-02 | 模型与 Skill 扩展 | 模型连接、模型源配置、批量拉取和模型优先的新手引导开始统一；补表格比较、行情报告、视频时序预览等 Skill；浏览器与 Android 支持上传文件夹 | [`3b62f1f2`](https://github.com/ybz21/Roami/commit/3b62f1f2)、[`5d66fbe8`](https://github.com/ybz21/Roami/commit/5d66fbe8)、[`143b0c61`](https://github.com/ybz21/Roami/commit/143b0c61)、[`840e1b77`](https://github.com/ybz21/Roami/commit/840e1b77) |
| 11-03 | OKR 首发 | OKR 工作区接入真实项目目标、每日观测、项目文件、按需 Main 对话和蜂群活动 | [`af8d5ece`](https://github.com/ybz21/Roami/commit/af8d5ece) |
| 11-03 | 蜂群架构切换 | 复用 Roami Main 和受管任务，统一 Main 编排、协作页签、群聊、看板及顶层 `roami swarm`，以稳定群 ID 关联 OKR | [`a135e5b1`](https://github.com/ybz21/Roami/commit/a135e5b1) |
| 11-04 至 11-06 | OKR 工作区 | 项目文件与团队执行形成闭环；精简目标工作区、固定 Main 对话；从聊天生成文件化看板和团队定义，并提供通用 Skill／项目模板 | [`c47b246c`](https://github.com/ybz21/Roami/commit/c47b246c)、[`987cfab9`](https://github.com/ybz21/Roami/commit/987cfab9)、[`f4792f0a`](https://github.com/ybz21/Roami/commit/f4792f0a)、[`d7e7bf7e`](https://github.com/ybz21/Roami/commit/d7e7bf7e) |
| 11-05 至 11-08 | 长期团队 | 保存长期成员身份、执行轮次和原生会话；按项目隔离团队与消息；持久收件箱、答复回执、成员结果和 Main 实际观察逐步落库 | [`3464cb00`](https://github.com/ybz21/Roami/commit/3464cb00)、[`6f1825a2`](https://github.com/ybz21/Roami/commit/6f1825a2)、[`558e9042`](https://github.com/ybz21/Roami/commit/558e9042)、[`6efd6a22`](https://github.com/ybz21/Roami/commit/6efd6a22)、[`19d2fe8b`](https://github.com/ybz21/Roami/commit/19d2fe8b) |
| 11-08 | 证据与恢复 | 稳定回执用于恢复观测、复盘与记忆追加；成员结果接回项目并强调幂等；增加发布协议与持久回执对账 | [`4c55fc70`](https://github.com/ybz21/Roami/commit/4c55fc70)、[`12eb2f1d`](https://github.com/ybz21/Roami/commit/12eb2f1d)、[`6062aecc`](https://github.com/ybz21/Roami/commit/6062aecc) |
| 11-08 至 11-09 | 语音与数据来源 | 语音配置归入模型并接入火山识别 2.0；OKR 项目增加初始化模板、SQLite 源库和发布登记动态采集 | [`dbaf1206`](https://github.com/ybz21/Roami/commit/dbaf1206)、[`49342fde`](https://github.com/ybz21/Roami/commit/49342fde)、[`442520b6`](https://github.com/ybz21/Roami/commit/442520b6) |
| 11-10 | 持久执行与资源 | 会话创建与收尾迁入持久后台流程；提供进程树、内存查看和手动结束进程；网关补 Key 管理 | [`1dc424bd`](https://github.com/ybz21/Roami/commit/1dc424bd)、[`e070516e`](https://github.com/ybz21/Roami/commit/e070516e)、[`d7168014`](https://github.com/ybz21/Roami/commit/d7168014) |
| 11-11 至 11-16 | 模型工作区 | 技能市场完善；模型侧增加用量审计、聚合路由、滚动监控、拖拽排序、能力目录和统一选模；`roami model list` 与 Agent 选模委派接入 | [`df82af9f`](https://github.com/ybz21/Roami/commit/df82af9f)、[`c3543841`](https://github.com/ybz21/Roami/commit/c3543841)、[`5874e60e`](https://github.com/ybz21/Roami/commit/5874e60e)、[`cdc44640`](https://github.com/ybz21/Roami/commit/cdc44640) |
| 11-14 | 团队控制与阅读 | 团队支持一键暂停／恢复；对话滑到顶部自动加载更早消息 | [`4a3fe2dd`](https://github.com/ybz21/Roami/commit/4a3fe2dd)、[`cb50f515`](https://github.com/ybz21/Roami/commit/cb50f515) |
| 11-18 | 上下文与原生 Main | 首页增加上下文整理与原文检索；Main 可在工作中平滑切换模型；原项目 Main 接入持久原生执行器 | [`a6effc25`](https://github.com/ybz21/Roami/commit/a6effc25)、[`04896ef0`](https://github.com/ybz21/Roami/commit/04896ef0)、[`180af763`](https://github.com/ybz21/Roami/commit/180af763) |
| 11-18 至 11-20 | 监督与接续 | 原成员接续 Claude 实例并保留历史；记录原生工具活动；Main 可自动调整长期成员；开工可创建互审会话并进行多轮复审 | [`661a4ec1`](https://github.com/ybz21/Roami/commit/661a4ec1)、[`51f80e87`](https://github.com/ybz21/Roami/commit/51f80e87)、[`f9d23abb`](https://github.com/ybz21/Roami/commit/f9d23abb)、[`6108a657`](https://github.com/ybz21/Roami/commit/6108a657) |
| 11-21 至 11-22 | 调度与诊断 | 模型工作区完善接入、调度与诊断；聚合和网关请求监控继续补强 | [`001649fb`](https://github.com/ybz21/Roami/commit/001649fb)、[`e6c7ea82`](https://github.com/ybz21/Roami/commit/e6c7ea82) |
| 11-23 | Agent 扩展 | 接入 Gemini CLI 与 Antigravity CLI，并补模型源请求头和模型标识 | [`ef5114c0`](https://github.com/ybz21/Roami/commit/ef5114c0)、[`e1fcedb4`](https://github.com/ybz21/Roami/commit/e1fcedb4)、[`8adf657a`](https://github.com/ybz21/Roami/commit/8adf657a) |
| 11-25 至 11-26 | 基线前收尾 | 独立终端页复用主工作台并补状态条；模型源、聚合删除、直接选模和会话初始化继续完善；基线提交优化已有 Main 对话打开速度 | [`9f164292`](https://github.com/ybz21/Roami/commit/9f164292)、[`55fb9fd9`](https://github.com/ybz21/Roami/commit/55fb9fd9)、[`00dda7c5`](https://github.com/ybz21/Roami/commit/00dda7c5)、[`eb1f9df1`](https://github.com/ybz21/Roami/commit/eb1f9df1) |

**阶段判断：** 11 月的新增重点是“围绕目标持续组织执行”和“统一选择、调度、观测模型”。“持续”来自持久身份、执行轮次、回执、恢复和暂停等机制，不应简化为“OKR 页面已经上线”。

**历史验证边界：** `a135e5b1` 的提交记录在当时仍注明真实模型闭环受 `MODEL_HTTP_401` 阻塞。这里用它证明 Main／团队架构进入代码库，不据此宣称当时已经完成真实模型闭环；后续状态须看后续提交与实际验收。

## 4. 功能域演进矩阵

这张表按能力域纵向阅读，避免把同一能力的首次出现和后续增强误写成两个独立产品。

| 功能域 | 首次成形 | 后续关键增强 | 基线代码／文档落点 |
|---|---|---|---|
| 会话与终端 | 05-27 并行任务原语 | 06 月 Go 重写；07 月子会话与稳定 ID；08 月懒恢复；09 月统一工作区；11 月持久后台创建／收尾 | [会话 CLI](../../internal/cli/)、[终端前端](../../frontend/src/components/terminal/)、[终端 UI](../../internal/terminalui/) |
| 蜂群与长期团队 | 05-27 多 Agent；06-15 Web 蜂群 | 07 月进入项目；11 月统一 Main、长期成员、执行轮次、消息回执和暂停恢复 | [Swarm CLI](../../internal/cli/swarm/)、[Swarm 前端](../../frontend/src/components/swarm/) |
| 文件、Git 与项目 | 06 月文件与上传下载；07-01 Monaco | 07 月 worktree、竞赛、项目主入口、Git 图；09 月任务工作区 | [项目前端](../../frontend/src/components/projects/)、[Worktree 后端](../../backend/worktree/)、[Git API](../../backend/api/git.go) |
| 浏览器与手机工具 | 06-16 Chrome 镜像；06-27 手机镜像 | 08 月 AVD 与多设备；10 月能力接入 ADB；11 月文件夹上传 | [浏览器后端](../../backend/browser/)、[手机后端](../../backend/phone/) |
| 移动客户端 | 06 月 PWA 与软键盘适配 | 08 月响应式；10 月 Android App、通知和小组件；后续持续完善二级页与恢复 | [Android](../../mobile/android/)、[手机部署](../deploy/mobile.md) |
| 插件与主动工作 | 07-07 插件系统 | 07 月主机监控、Cron、飞书管家；09 月 Cron 结果、自检和 Keepalive | [插件目录](../../plugins/)、[插件开发](../design/plugin/README.md) |
| 内置助手、任务与记忆 | 10-19 主智能体运行时 | 10 月任务／消息／记忆／产物工作台；11 月上下文检索、原生 Main 与可追溯执行 | [Agent 运行时](../../agent-runtime/src/roami_agent/)、[助手前端](../../frontend/src/components/agent/) |
| 能力中心与模型 | 10-21 能力中心 | 10 月开放市场与本地模型代理；11 月模型源、聚合、路由、选模、用量和请求诊断 | [能力中心](../../frontend/src/components/capabilities/)、[模型网关](../../internal/modelgateway/)、[统一 CLI](../../cmd/roami/) |
| 多机与传输 | 07-17 集群后端；07-20 P2P 后端 | 08 月多机前端与手机切换；09 月 P2P 优选与更多文件类型 | [集群后端](../../backend/cluster/)、[集群前端](../../frontend/src/components/cluster/) |
| 数据与可靠性 | 07 月稳定 ID；08-12 `meta.db` | 08 月内存护栏与懒恢复；09 月重启接回；11 月持久后台流程、回执和进程治理 | [统一 CLI 与存储](../../cmd/roami/)、[安装与恢复](../install/README.md) |
| OKR 与 RSI | 10 月 RSI 实验；11-03 OKR 工作区 | 11 月项目文件、团队、回执与观测复盘连接；完整自动闭环仍在路线图 | [OKR 设计](../design/20261030-okr每日行动/)、[Agent 框架边界](../design/20261104-okr-studio-project-ownership/responsibility-boundary.md) |

## 5. 版本标签详表

标签指向提交只是版本切点，目标提交的主题不等于该版本全部内容；版本能力应结合标签说明和其可达历史理解。

| 标签 | 指向提交及作者日期 | 标签／切点证据 | 讲法 |
|---|---|---|---|
| `v0.1.0-rc.1` | `4fc3e947`，07-09 | Roam 首个本地 RC 标签；目标提交修复 release 的 Chrome 打包路径并按 tag 标记 prerelease | “首个预发布切点”，不要写成稳定版 |
| `v0.1.0-rc.2` | `5381fd33`，07-09 | 标签说明与目标提交明确包含 macOS launchd、关于页版本／检测更新及 Chrome/ADB 安装 | “补齐 macOS 常驻与更新入口的 RC” |
| `v0.2.0-rc.1` | `ef24119f`，09-08 | 标签说明列出 Roami 更名、统一 CLI、Cron 结果、任务工作区、自检、语音和内存治理 | “统一入口与工作区的预发布收口” |
| `v0.2.0-rc.2` | `9e57790f`，10-23 | 标签说明为 complete agent runtime and supervised installation；目标提交是 README 品牌海报更新 | “完整 Agent 运行时与监督安装的预发布切点” |
| `v0.2.1` | `dc22be9e`，10-26 | 非 RC 标签；目标提交缩减首屏资源与非首页聊天预取 | “首屏性能优化版本”，不扩写成新功能版本 |

## 6. 当前产品形态对照

基线 [README](../../README.zh-CN.md) 将产品定义为可从手机、平板和电脑访问的自托管远程控制台：专业 Agent、代码、文件和工具运行在开发机，客户端用于发起任务、跟踪进展、查看结果和接管。

[完整功能清单](../features.zh-CN.md) 按 2026-10-23 的主线代码列出 23 类能力，适合查询 10 月下旬前的详细功能；11 月变化由本文阶段六和全量提交补充。讲稿中的“多智能体工作台”是对这些能力的概括，不是另起一个独立产品名称。

可将当前产品拆成四层理解：

1. **接入层**：Web/PWA、Android App、统一 CLI，以及可选多机中心。
2. **工作层**：项目、任务、持久会话、worktree、文件／Git、终端和远程工具镜像。
3. **智能层**：内置 Main、专业 Agent、蜂群／长期团队、任务交付、记忆与上下文。
4. **能力与治理层**：插件、Skill、MCP、CLI、模型网关、身份权限、持久状态、回执和恢复。

## 7. 不与路线图混淆

[Roadmap](../../ROADMAP.zh-CN.md) 明确将以下三项列为下一阶段，而非完整交付：

1. **RSI：** 已有实验流水线、问题复测、运行记录和模型准入等基础；尚不能宣称已经形成可持续评估、生效、跟踪和回滚的完整自进化闭环。
2. **通用消息数字分身：** 已有飞书机器人桥、消息、任务和通知基础；尚不能宣称 SuperWork、多渠道统一接入及自动回复／派活已经完整交付。
3. **OKR 自动执行：** 已有 OKR 工作区、项目文件、长期团队、日程和回执基础；尚不能宣称从自动拆解到每日行动、KR 更新和复盘的完整闭环已经交付。

另外三项条件边界也应保留：

- P2P 是可选能力，实际直连取决于网络条件，并保留回退路径。
- iOS 镜像和 Linux X11 Computer Use 在当前功能清单中属于条件性或实验性能力。
- 专业 Agent 的安装、登录、额度、模型和对话解析依赖对应 CLI、服务商和宿主环境；“有接入代码”不等于任何机器上无需配置即可使用。

因此讲稿使用“已有基础”“开始围绕长期目标组织”等表述，不使用“已经实现完整自进化／数字分身／OKR 自动执行”。
