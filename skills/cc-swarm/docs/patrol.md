# 巡检 (patrol)

巡检是 cc-swarm 的核心循环，所有其他能力都建立在巡检之上。

## 两种作用域

- **全局监护**（无参数）：监护所有 `cc-*` 前缀会话。
- **蜂群作用域**（`--swarm <名>`，由 `roami session swarm adopt` 注入）：**只**监护该蜂群的成员。

### 蜂群作用域怎么探测成员

被 `--swarm <名>` 调起时，**不要**用 `roami session ls` 扫全局，而是读蜂群的三个面：

```bash
roami session swarm status <名>            # 成员运行态 + 依赖 + 挂起
roami session swarm board  <名>            # 看板：谁负责什么、卡在哪一列
roami session swarm listen <名> --as master --once # 广场增量 + @master/@all/human 优先级标注 + 状态摘要
roami session swarm feed   <名> --since <上次id>   # 兜底：直接读广场完成/提问/阻塞 的结构化播报
roami session swarm collect <名>           # (兜底)各成员的终端输出
```

> **巡检信号优先读「广场 + 看板」，不要纯抓终端。** 成员把进展/提问/阻塞结构化地发到广场、
> 把卡片在看板上流转，比 capture 屏幕鲁棒得多；终端 capture 只在需要深看某成员在干嘛时兜底。

成员会话名形如 `<名>-<成员>`。监护时：
- **读广场**：每轮优先 `swarm listen <名> --as master --once` 拉新消息；若需要手动控制游标，再用 `swarm feed <名> --since <上次id>`——
  - `author=human` 或文本含 `@master` / `@all` → **最高优先级**。即使蜂群已经 `done`，也要判断是追问、追加需求、返工、叫停还是闲聊；需要继续工作就重开看板卡/派活，并用 `swarm say --kind decide --re <id>` 回写处理决定；
  - `--kind block`（有人卡住）→ 最高优先，介入排障；
  - `--kind ask`（有人提问）→ 答疑，可 `swarm say <名> --kind decide --re <id> "<裁决>"`；
  - `--kind done`（完成播报）→ 去 review，通过后推进看板 + 解锁下游（见下）。
- **@xx 提及**：`@master` 给你处理；`@human` 表示需要人拍板；`@all` 全员都读但仍由你做全局调度；`@<成员>` 点名成员。给特定成员发消息优先用 `swarm say <名> --to <成员> --kind decide "<指令>"`，不要让 worker 自行给别人派活。
- **读看板**：`swarm board <名>` 看任务全貌——`doing` 太久不动的去看一眼，`review` 列的去审，`blocked` 列的去解。
- **目标对照**：`swarm status` 顶部的「目标」就是验收基准，集成时逐条核对。
- **依赖解锁（关键闭环）**：带依赖且依赖未满足的成员会被 ttmux **挂起为 pending**（`swarm status` 底部「挂起(等依赖)」段列出，`依赖→ X`）。解锁靠你打「完成」标记驱动：
  - **agent 成员是长驻会话**（claude 不退出），脚本判不出它「完成」。所以**当你读 capture 判定某成员 X 真的完成了**（输出了总结、idle 在空 prompt、产出对照需求 OK），就执行：
    ```bash
    roami session swarm done <名> X        # 标记成员 X 完成 → 自动级联解锁依赖 X 的下游成员
    ```
    这一步是把「AI 的完成判断」喂给门控的**唯一**入口，不打标 → 下游永远挂着。
  - 打标后 `roami session swarm status <名>` 每轮也会顺手自动解锁就绪的挂起成员；也可显式 `roami session swarm activate <名>`。
  - task 成员若命令会退出，脚本能自动判完成；判不准时同样用 `swarm done <名> X` 兜底。
  - 依赖成员**失败但你决定继续**：`roami session swarm activate <名> X --force` 强制解锁 X（无视依赖）。
  - X 没完成前**不要**手动 spawn/催挂起成员——交给门控。
- **自我排除**：跳过指挥会话自己（`supervisor`，通常 `cc-<名>`）。
- **闭环**：每个成员完成就 `swarm done <名> <成员>` 打标解锁下游；全部成员完成（`swarm status` 无挂起残留）并对照目标验收通过后，`roami session swarm done <名>`（不带成员=标记整群完成），再汇报用户。

> 蜂群作用域下，下面流程里的「`cc-*` 会话」一律替换成「该蜂群的成员会话」。

## 流程

### Step 1: 探测 session

```bash
roami session ls
```

从输出中提取所有 `cc-*` 前缀的会话名，排除自身（通常是 `cc-神` 或运行 cc-swarm 的 session）。

> 蜂群作用域（`--swarm <名>`）下改为：`roami session swarm status <名>` 读成员清单，只盯这些成员。

### Step 2: 抓取上下文

对每个 session：

```bash
roami session capture <session> --lines 40
```

抓最近 40 行通常够用。但注意：
- 如果 capture 结果全是空行，说明 tmux 窗口有大量空白（常见于 `/clear` 之后），**加大到 `--lines 80` 再试**
- 如果需要看完整错误日志，加到 `--lines 100`
- 过滤空行后再分析：`tail -30` 可能全空，`grep -v "^$"` 后才能看到实际内容

### Step 3: AI 分析

**不要用 grep/正则** 来判断状态。把 capture 的输出当文本阅读，理解：

- 这个 session 上一个指令是什么？
- 它现在在做什么？写代码？等审批？报错了？
- 它的产出合理吗？方向对吗？
- 它需要什么帮助？

### Step 4: 输出状态表

每轮巡检输出一个状态表给用户：

```
| session    | 状态     | 上下文摘要                    | 决策          |
|------------|----------|-------------------------------|---------------|
| cc-oauth   | ✅ 完成  | OAuth 测试 29 case 全过        | → 催 review   |
| cc-数据    | 🔄 执行中 | 写 tickflow fallback 重构     | → 不干预      |
| cc-回测    | ⏳ 等审批 | 要创建 test_backtest_job.py   | → 批准        |
```

### Step 5: 执行决策

按优先级：
1. **等审批的** → 先处理，不然会卡住整个 session
2. **有待发命令的** → prompt 里有用户（或上轮 cc-swarm）输入的文字但没按 Enter，帮它发 `tmux send-keys -t <session> Enter`
3. **在提问的** → 回答问题，解除阻塞
4. **出错的** → 诊断修复
5. **已完成的** → 安排下一步（测试/review/commit）；蜂群作用域下，确认完成后 `roami session swarm done <名> <成员>` 打标，解锁等它的下游
6. **执行中的** → 跳过

### Step 6: 间隔等待

```bash
sleep 30  # 默认 30 秒
```

如果当前活跃 session 多（>3 个），间隔拉长到 60 秒，减少自身 API 消耗。

## Agent Loop（核心）

cc-swarm 的默认运行方式是 **持续循环巡检**，不是跑一次就停。

### 循环结构

```
初始化:
  mkdir -p ~/.local/share/ttmux/cc-swarm
  读取所有已有记忆文件，恢复上下文

循环:
  while true:
    1. 探测 session (roami session ls)
    2. 读记忆 + capture
    3. AI 分析 + 决策
    4. 执行（审批/发指令/review）
    5. 更新记忆
    6. 输出本轮摘要给用户
    7. sleep (动态间隔)
```

### 动态间隔

间隔不是固定的，根据当前状态调整：

| 状态 | 间隔 | 原因 |
|------|------|------|
| 有 session 等审批 | 10s | 审批阻塞，快速响应 |
| 多个 session 活跃执行中 | 30s | 正常节奏 |
| 全部空闲或全完成 | 60s | 没什么急事 |
| 遇到 429 | 60-90s | 降低负载 |

### 循环感知

每轮循环要感知：
- **哪些 session 是新的？**（上轮没有，这轮出现了）→ 创建记忆
- **哪些 session 消失了？**（被 kill 了）→ 标记记忆为 done
- **哪些 session 状态变了？**（从执行中变成空闲）→ 安排下一步
- **上轮发的指令执行了吗？**（对比记忆中的"已发指令"和当前 capture）

### 退出条件

循环不会自己停，除非：
- 用户手动叫停（发消息 "停" / Ctrl+C）
- 所有 session 都标记为 done 且没有新 session 出现
- 遇到不可恢复的错误

## 注意

- 一轮巡检中，**最多给 2 个空闲 session 发新指令**，避免同时激活太多
- 如果上一轮刚给某个 session 发了指令，这一轮不要重复发（读记忆判断）
- capture 的输出可能包含 ANSI 颜色码，忽略它们关注实际内容
- **每轮巡检结束输出一行简短摘要**，让用户知道 cc-swarm 还活着在干活
