# 可靠性测试用例（R1 内存护栏 / R2 会话懒恢复）

```
bash tests/reliability_e2e.sh            # 全跑
bash tests/reliability_e2e.sh guard      # 只跑内存护栏
bash tests/reliability_e2e.sh revive     # 只跑懒恢复
bash tests/reliability_e2e.sh ui         # 只跑浏览器那几条
```

设计稿：[`docs/design/reliability/memory-guard.html`](../docs/design/reliability/memory-guard.html) ·
[`session-restore.html`](../docs/design/reliability/session-restore.html)

## 为什么必须是 e2e

这两块的坑**几乎全在接缝上**，单测一个都拦不住：

| 实际踩过的坑 | 单测为什么拦不住 |
|---|---|
| `systemctl set-property` 对还没注册完的 transient scope **静默成功**（exit 0，属性没落上） | 要真起 tmux 会话、真读 `memory.max` 才看得见 |
| cgroup 目录随会话消失，"等发现它没了再读 `memory.events`"读不到 | 要真把一个会话压到撞顶 |
| Node 按 cgroup 限额把 V8 默认堆砍半，构建 OOM 且 `oom_kill=0` | 要真跑一次前端构建 |
| `ls --json` 和 `ls --tree` 是两份实现，补一处漏一处 | 两个出口都得真调 |
| 会话列表看不出休眠态，点下去才发现要重开 | 要真渲染出来看 |

所以用例都真起会话、真读 cgroup、真点页面。跑一轮约 1–2 分钟。

## R1 内存护栏

| # | 用例 | 断言 | 守的是什么 |
|---|---|---|---|
| **G0** | 护栏装不上时建会话 | 会话照常建出来 | 降级不能变成"开不出会话"。只在 cgroup v1 / 无 systemd 的机器上跑（如 jetson） |
| **G1** | **连建 5 个**会话 | 上限 5/5 生效 | `set-property` 静默成功的竞态。一次成功说明不了问题——修之前是"四次里成两次" |
| **G2** | 额度设 6G | `max=6G` 且 `high=4.5G` | 6G 是特意选的：75% 不整除。按单位做整数除法会截成 4G，而 8G 正好整除、看不出来 |
| **G3** | 会话内进程吃爆 300M 上限 | `oom_kill≥1`、`oom_group_kill=0`、**会话存活** | 护栏的立身之本。它要是把会话也带走，就和 `global_oom` 没区别了 |
| **G4** | 撞顶后查台账 | `oom_kills≥1`、`peak_rss` 有值 | cgroup 目录随会话消失，计数必须**趁活着时**落库 |
| **G5** | 结束该会话 | `died_reason='oom'` | 要能和笼统的 `killed` 分开，否则下次还得翻内核日志 |
| **G6** | `ROAM_SESSION_MEM_MAX=off` | `memory.max=max` | "我就是要跑个吃 20G 的东西"这个口子得真能开 |

## R2 会话懒恢复

用例先造一个休眠会话：建 → kill → 把台账改成 `died_reason='host-restart'` + 对不上的 epoch。
不能真去重启机器，但那两个字段就是"被重启带走"的定义。

| # | 用例 | 断言 | 守的是什么 |
|---|---|---|---|
| **V1** | 休眠会话在 `ls --json` 里 | `state=dormant` | 少了它，前端 `dropDeadTokens` 会把上次开着的终端标签全丢掉——用户连点击的机会都没有 |
| **V2** | 同一条在 `ls --tree` 里 | 也是 `dormant` | **会话列表走的正是 tree 接口**。两份实现各补各的，就出现"概览里有、点进项目又没了" |
| **V3** | `db revive` | 新会话建出、`restored_from` 指回原会话 | 重开的是壳不是现场；旧行保持 dead，历史不被改写 |
| **V4** | 恢复后查台账 | `label` 非空 | 兜底名只在显示时算的话，恢复前后是两个名字（列表里叫 XiaoHui，点开变成裸 id） |
| **V5** | 再 revive 一次 | 复用同一个会话（`reused`） | 幂等。double-checked locking 没兜住就会点一次多一个 |
| **V6** | 恢复后再看列表 | 它不再是 dormant | `restored_from` 被占用后就该排除，否则会重复恢复 |
| **V7** | 显式 `ttmux kill --yes` | `died_reason='killed'` 且**不进**休眠列表 | 你亲手杀掉的会话自己回来，比消失更让人恼火 |

## UI（chrome CLI）

跑之前需要 Chrome 起着（`roami chrome goto <url>` 一次即可）。用例会自己登录、自己造休眠会话。

| # | 用例 | 断言 | 守的是什么 |
|---|---|---|---|
| **U0** | 打开会话页 | 渲染出 ≥1 行 | 冒烟。掉登录会自愈（从 `.env` 读口令登回去） |
| **U1** | 造一个休眠会话后看列表 | 有"休眠"标签，且**空心点数量与之相等** | **这次 bug 的直接回归**。修之前休眠会话和活会话长得一模一样、标签同样写"空闲中"，用户点下去才发现要重开 |
| **U2** | 活会话 | 渲染出内存条 | `treeNode` 漏 `mem` 字段的话这里恒为 0 |
| **U3** | 中心页展开「这台机器」 | 画出 Swap 条，且**零个** `#f5222d`/`#faad14` | swap 用满是整机卡死的前兆（2026-08-12 本机就这么冻死的：ping 通、ssh 进不去），它一度画成固定灰色小条，98% 和 5% 长得一样。进度条颜色是行内 style，`hover:check` 那类静态扫描看不见，tokens-only 在这儿最容易破防。需要 `HUB_URL`/`HUB_PASSWORD` |

## 写用例时踩的两个坑

两个都不是产品的问题，但会让测试**假绿或假红**，记在这里免得再犯：

**① `died_at` 必须写 RFC3339 本地时区。** `Dormant()` 用 `ORDER BY died_at DESC LIMIT 1`
挑"最新一代"，那是**字符串**比较。sqlite 的 `datetime('now')` 给的是
`2026-08-23 10:42:15`（空格分隔、UTC），而真实值是 `2026-08-23T10:43:33+08:00`——
空格(0x20) < `T`(0x54)，伪造的行永远排在真实那批后面，**这条测试数据自己把自己排除了**。

**② 改台账前要等 tmux 真的收走会话，且写完要回读确认。** 后端每几秒轮询一次 `/sessions`，
`Reconcile` 见"死行上又冒出同名会话"会把它复活成 live + 当前 epoch，刚写的
`host-restart` 就没了（实测 `died_reason` 变回 `killed`，V1–V4 集体假红）。
这和产品里 `memguard.Apply` 必须回读 `memory.max` 是同一个道理：**有别的写者在并发改，
"命令返回 0" 证明不了状态**。

## 收尾

会话都带 `e2e-rel-<pid>` 前缀，`trap EXIT` 一并清掉，不碰用户自己的会话。
但**台账里的伪造行不会自动清**（它们是数据不是进程）——攒多了会混进休眠列表，
定期清一次：

```sql
DELETE FROM sessions WHERE restored_from IN (SELECT id FROM sessions WHERE tmux_epoch LIKE '%-old');
DELETE FROM sessions WHERE tmux_epoch LIKE '%-old';
```
