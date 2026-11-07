# 会话内存误杀排查与恢复

## Product Design

内存测试不得改变开发会话或 tmux server 的内存上限。只有确认 pane 已进入独立的
`tmux-spawn-*.scope` 后才能设置硬限和软限；隔离未完成时等待重试，无法确认则返回错误。

恢复会话沿用原工作目录和已核对的 Codex 对话 ID。恢复的是终端入口与对话记录，
被终止的进程无法原地恢复。

### 告警、暂停与继续的界面

| 状态 | 触发条件 | 用户看到的内容与动作 |
| --- | --- | --- |
| 正常 | 用量低于上限的 60% | 列表保留内存条；终端不显示告警条。 |
| 告警 | 用量达到 60% | 黄色状态条显示当前用量、上限、百分比和“暂停”；后台会话弹出提醒，可“查看会话”。消息页保留记录。 |
| 自动暂停 | 用量达到 80%，或整机可用内存不足 12% / PSI 达到 10% 时选中较大会话 | 显示“会话已暂停，进程和终端已保留”，动作变为“继续”；列表标记“已暂停”，不再显示正在运行或待输入。 |
| 手动暂停 | 用户点“暂停” | 冻结同一会话所有 pane 的进程和后代，包括脱离进程组的子进程；保持终端画面。 |
| 手动继续 | 用户点“继续” | 恢复原进程。30 秒内不再自动暂停；仍处于告警线之上时保留黄色告警，超过宽限期且仍达暂停线则再次暂停。 |
| 暂停失败 | 环境不支持、窗格共用或内核状态未完成 | 说明自动暂停未成功，保留关闭不需要会话的处理建议；不把请求成功当作冻结成功。 |

整机压力策略只选至少 512MiB 的最大会话，一轮已有因压力暂停的会话时，不继续逐个冻结。
暂停不立即释放内存；硬上限、内核 OOM 和系统 oomd 仍可能终止进程。

桌面状态条位于会话工具栏下，手机位于固定返回栏下。当前正在查看的会话只显示状态条，
避免重复弹窗遮挡“继续”；后台会话通过全局提醒和消息页可达。

| 界面证据 | 桌面 | Android 真机 |
| --- | --- | --- |
| 改前，同一终端缺少内存状态和恢复动作 | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/desktop-before.png) | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/phone-before.png) |
| 正常，释放内存后告警消失 | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/desktop-normal.png) | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/phone-normal.png) |
| 告警：175MiB / 256MiB，68% | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/desktop-warning.png) | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/phone-warning.png) |
| 自动暂停：227MiB / 256MiB，89% | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/desktop-paused.png) | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/phone-paused.png) |
| 手动继续：仍超告警线，原进程继续运行 | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/desktop-resumed.png) | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/phone-resumed.png) |

## User Stories

- 开发者使用 128MiB 限额验证内存保护时，当前工作会话与测试服务器继续运行。
- pane 还在父进程的 scope 内时，不给父 scope 设置测试限额。
- 会话消失后，能够找到原工作树、未提交修改和原对话，并区分进程退出与目录删除。

## Technical Design

### 已核对的退出原因

| 时间（2026-11-07，Asia/Shanghai） | 会话 | 证据与结论 |
| --- | --- | --- |
| 08:09:07 | `2026-1107-0003-00h8`，会话内存保护 | `systemd-oomd` 终止 `tmux-spawn-5086dcab-8957-4871-8809-c2a0eff87f65.scope` 中的 11 个进程。用户服务内存压力持续超过 20 秒，达到 55.11%，阈值为 50%。被选 scope 当时占用 391.1MiB，压力 Avg10 为 60.24%；台账记录峰值 876236800 字节。该次不是单会话撞硬上限。 |
| 16:47:25 | `2026-1107-1614-00ie`，内存冻结查找 | 内核调用栈包含 `memory_max_write`。`tmux-spawn-02c13041-d000-4d19-bb1f-f165afa86437.scope` 的硬限被设为 131072KiB，当时用量 445136KiB。Codex、Node、测试服务和 shell 随后被 cgroup OOM 终止。原对话最后一个命令正在以 `ROAM_SESSION_MEM_MAX=128M` 创建测试会话。 |

08:09 的全局压力另有原对话记录：多个 OKR 完整测试把临时目录放进 `/dev/shm`，
当时占用约 14.4GiB，8GiB 磁盘交换区接近用满。原会话已在中断前迁移其中一批目录。
这说明不能仅凭当前 Agent 的 RSS 判断是否会被 oomd 选中；不能据此断言 Agent 有堆泄漏。

16:47 的测试使用了私有 tmux socket，但私有 server 继承了调用者的 cgroup。
OOM 进程列表同时包含工作 Codex、测试 tmux server（PID 2879398）和测试服务。
原 `Apply` 只检查 scope 名以 `.scope` 结尾，未确认其与控制进程、pane 父进程隔离。
pane 迁移未完成或失败时，继承的工作 scope 因而会被误认为测试 pane 的 scope。
现有日志不能进一步区分当次迁移是延迟还是失败。

### 代码与模块

- `internal/memguard/pane-scope.go`：读取 pane、控制进程和 pane 父进程的 cgroup；
  只允许独立的 `tmux-spawn-*.scope`。拒绝控制进程/父进程所在 scope 及其祖先，
  缺少隔离证据也拒绝。
- `internal/memguard/memguard.go`：`Apply` 和 `SetHigh` 每次写入前使用同一检查。
  保留现有 2 秒重试与内核回读确认，以便 pane 迁移完成后正常设置限额。
- `internal/memguard/pane-scope_test.go`：覆盖控制进程、父进程、嵌套 cgroup、未知路径和
  正常独立 pane。用替身 `systemctl` 验证对自身设硬限和软限均不会执行写入命令。
- `internal/mempause` 选择告警和暂停目标；`memguard/freezer.go` 写入并回读内核冻结状态；
  `tmuxruntime/pause.go` 串行化 CLI/HTTP 操作，验证共用窗格并在部分失败时回滚。
- `session.Collect` 在现有采集链中执行策略；概览、项目与列表统一输出内存状态。
  `memalert` 将状态变化写入收件箱，并用事务保证失败可重试。
- `SessionMemoryControl` 复用共享概览订阅，提供全局提醒、终端状态条和暂停/继续按钮；
  桌面列表、手机项目列表、切换页和消息页使用同一状态，无新增逐会话轮询。

### 恢复结果

- 功能工作树：`.worktrees/2026-1107-0003-00h8`，分支 `feat/session-memory-pause`。
  34 个已暂存修改文件仍在（837 行新增、66 行删除），目录没有被删除。
- 原功能入口恢复为 `2026-1107-1659-00ip`，名称“会话内存保护”，关联原 Codex 对话
  `01a1b199-fee8-7bb2-ac6e-d6cec74ac054`。
- 最近查找入口恢复为 `2026-1107-1701-00iq`，名称“内存冻结查找”，关联原 Codex 对话
  `01a1b512-d5d9-72c3-8231-206ac254f0d8`。
- 两个入口的恢复命令均已预填；由用户回车接回原对话。
- 原功能补丁与现场日志另保存在 `/tmp/roami-memory-recovery-20261107/`，不提交一次性产物。

## Acceptance Evidence

- `scripts/dev/quality/check.sh quick` 通过，包括全量 Go 测试、前端静态检查和提交策略检查。
- `go test ./internal/memguard ./internal/memthrottle ./internal/tmuxruntime ./internal/session` 通过。
- `go test ./internal/memguard -run 'TestMemory' -v` 通过；自身硬限/软限测试确认没有调用
  `systemctl` 写入，测试替身不会改动真实 cgroup。
- 构建修复后的 CLI，在 `scripts/dev/isolated-roami.sh` 记录的私有实例中连续创建并关闭
  4 个 128MiB 测试会话：4 个 pane 均进入不同的独立 scope，`memory.max` 均回读为
  134217728；工作会话前后均为 13304680448，测试 server 保持存活。
  结果保存在 `/tmp/roami-memory-recovery-20261107/scope-regression.json`。
- 已将原告警与冻结功能的 34 个文件接入本 PR，保留限额隔离修复。
  运行中的正式 Roami 未被替换，验证使用独立测试实例。
- 完整功能验证：`scripts/dev/quality/check.sh full`、前端 typecheck/i18n/hover/build
  以及 212 个测试文件中的 1551 个测试全部通过。
- 真机验证：Redmi Note 8（`216d6a43`），LAN HTTPS。ADB 点按继续与手动暂停有效；
  原 PID 和启动时间保持不变，父进程及分离子进程的心跳随冻结停止、随继续恢复。
  保持用量 89% 时，30 秒宽限期后再次自动暂停；释放至约 43MiB 后告警消失。
- 布局验证：1280、1920、2560、3440 CSS px 下分别打开/关闭侧栏，均无文档横向溢出，
  终端有效高度为 915px，状态条和按钮在可用区域内且命中正确。
  手机返回栏为 60 CSS px，继续按钮命中区至少 44 CSS px，无重复告警弹窗遮挡。
- 中英文暂停文案均在真实浏览器中检查，语言已恢复为简体中文。

## 自动回收、上下文整理与系统压缩

### Product Design

告警后先尝试回收，再按最新用量判断是否需要暂停。系统压缩与 Agent 上下文整理分别展示，
不会把 `/compact` 已提交、请求回收的字节数或普通磁盘交换说成“已节省内存”。

| 能力 | 自动策略 | 界面与限制 |
| --- | --- | --- |
| 冷内存回收 | 告警或整机压力时，每轮选择一个较大会话；同会话至少间隔 1 分钟。每轮最多请求 128MiB，且不超过当前用量的 1/8、交换区余量的一半。 | 状态条提供“回收内存”，按实际驻留内存下降量与交换页增量报告结果；交换区不足、不支持或无有效回收分别说明，保留暂停保护。 |
| Agent 上下文整理 | Codex / Claude 前台交互 TUI，告警但尚未达到 80%；后台未打开、空闲、输入可确认为空时提交 `/compact`，至少间隔 10 分钟。 | 状态条提供“整理上下文”；冻结或运行中禁用。忙碌、草稿、权限交互、未知界面和多 pane 均推迟；不自动重启 Agent。仅表示请求已提交，不保证 RSS 下降。 |
| zram 压缩交换 | 管理员显式安装后由系统透明压缩，重启后恢复。默认逻辑容量为物理内存的一半，压缩区实际内存上限为物理内存的 1/8。 | 设置 → 会话内存显示自动开关、zram/zswap 状态、交换区余量及 zram 原始量、包含开销的实际占用与节省量。未启用时可下载脚本，不在 Web 服务中提权。 |

两项自动策略默认打开，分别通过 `ROAM_MEMORY_RECLAIM`、`ROAM_MEMORY_COMPACT` 保存设置；
`off`、`0`、`false` 可关闭。手动继续后的 30 秒宽限期也跳过自动整理。

### User Stories

- 会话过线时先尝试有限回收；确实回收不足时仍暂停，保留原进程。
- 用户输入中的草稿、正在执行的任务和权限确认不会被自动插入 `/compact`。
- 用户能看到主机是否真的开启压缩、当前交换区是否有余量，并获得本节点可运行的安装脚本。
- 手机可保存自动整理开关、手动回收并继续冻结的会话。

### Technical Design

- `internal/memrelief` 负责候选选择、字节预算、冷却和空输入判断。
- `tmuxruntime/memory-recovery.go` 持久化结果，与暂停/继续、CLI 提交共用会话锁；
  前台进程组校验、两次一致的终端快照和输入检查后才能提交整理命令。
  提交前记录冷却；结果未知时不自动重发。
- `session.Collect` 使用既有概览采样，回收后重新采样并更新告警/暂停判断；没有新增逐会话轮询。
- `memguard.Reclaim` 同样拒绝控制进程或继承的工作 scope。
- `memguard/compression.go` 读取活跃 zram 设备的 `mm_stat`，使用 `mem_used_total` 计算实际占用，
  不假定固定压缩比；zswap 只报告开关状态。
- 下载脚本的唯一来源为嵌入二进制的 `internal/memguard/zram-setup.sh`。
  新安装入口为设置页下载或 `roami session memory-setup-script`；原有开发脚本本轮未改动。
  新脚本验证参数、保留已有压缩后端与磁盘 swap、为自有设备记录归属；
  停止时必须成功停用该设备后才重置，禁止全局 `swapoff -a`。
- CLI 增加 `reclaim`、`compact`、`memory-status` 和 `memory-setup-script`；
  HTTP 提供对应恢复动作、状态与脚本下载，沿用登录鉴权与节点入口。

参考：[Linux zram](https://docs.kernel.org/admin-guide/blockdev/zram.html)、
[cgroup v2 memory.reclaim](https://docs.kernel.org/admin-guide/cgroup-v2.html)、
[Claude Code 内存排查](https://code.claude.com/docs/en/troubleshooting#high-cpu-or-memory-usage)、
[Codex compact](https://learn.chatgpt.com/docs/developer-commands#keep-transcripts-lean-with-compact)。

### Acceptance Evidence

- 单测覆盖回收预算、冷却、恢复宽限、暂停跳过、空闲输入与草稿/忙碌/权限拒绝、
  活跃压缩设备与开销计算、脚本参数、错误码保留和设置开关持久化。
- 独立实例中的真实 Codex 接收到 `/compact` 并生成上下文摘要；界面只显示“已请求整理”。
- 无压缩且磁盘 swap 余量不足时，告警显示未回收原因；测试会话达到约 227MiB / 256MiB 后冻结。
  原 PID `2223527` 的启动时间不变，父进程和分离子进程心跳停止；ADB 点“继续”后均恢复。
- 桌面 1280、1920、2560、3440 CSS px，侧栏分别开启/关闭：无文档溢出，终端有效高度 900px。
  Redmi Note 8 真机完成自动开关点按与保存、滚动、回收、继续；动作命中区为 44 CSS px。
- 本机没有无密码管理员权限，zram 尚未启用；已验证下载和 dry-run，不声称完成内核压缩实测。
  管理员可下载后运行 `sudo bash roami-zram-setup.sh`。实际压缩数据解析使用内核格式夹具验证。
- 最终前端全量测试：213 个文件、1555 项测试通过；完整质量检查、类型、i18n、hover 和构建通过。
- 真实 Codex 输入 `retain-this-draft` 后，整理返回 `MEMORY_COMPACT_DEFERRED`；草稿未被提交或覆盖。

| 新增界面 | 桌面 | Android 真机 |
| --- | --- | --- |
| 回收不足告警 | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/desktop-reclaim-warning.png) | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/phone-reclaim-warning.png) |
| 保留冻结保护 | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/desktop-reclaim-paused.png) | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/phone-reclaim-paused.png) |
| 整理与系统压缩设置 | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/desktop-recovery-settings.png) | [截图](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-768/phone-recovery-settings.png) |
