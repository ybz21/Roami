# 开子会话 (spawn)

为每个子任务开一个 Claude Code 会话并把任务派进去。这是「包工头」把活分出去的一步。

## 两种方式：交互式 vs 无人值守

| | 交互式（默认，推荐） | 无人值守（headless） |
|---|---|---|
| 启动 | `roami session new` + 发 `claude` | `roami session agent spawn`（跑 `claude -p`） |
| 权限 | 会弹审批菜单，由 cc-swarm 巡检审批 | `--dangerously-skip-permissions` 自动放行 |
| 适合 | 需要监护、review、改方向的开发任务 | 边界清晰、可信、一次性的批量小任务 |
| 结束 | 一直开着，可追加指令 | 跑完即退出 |

**蜂群的主力是交互式** —— 因为 cc-swarm 的审批/巡检/review/纠偏能力都建立在交互式会话上。
无人值守只用于那种"绝对安全、不需要盯、跑完就行"的活。

## 交互式开会话（主力流程）

### Step 1: 把任务写成文件，避免引号转义地狱

子任务的 prompt 通常较长、含特殊字符，直接拼到命令行会被引号坑。先落盘：

```bash
mkdir -p ~/.roami/cc-swarm/tasks
```

用 Write 把每个子任务的完整指令写到 `~/.roami/cc-swarm/tasks/<name>.md`。
内容应包含（**给子会话的，不是给 cc-swarm 的**）：

```markdown
你负责子任务 <T1·backend-auth>。

## 目标
<这个子任务要做成什么>

## 范围 / 边界
- 只动 backend/ 目录
- 提供给前端的 API 契约：POST /auth/login → {token}

## 约束
- 复用现有 backend/db.py 的连接
- 用项目已有的 pytest 风格

## 验收
- [ ] 三个端点可跑通
- [ ] 写 pytest 覆盖核心路径

完成后输出一句话总结你改了哪些文件、API 契约是什么。
```

> 子任务文件要**自包含**：子会话看不到 `_spec.md`，它需要的上下文都得塞进这份指令里。

### Step 2: 创建会话并启动交互式 claude

```bash
roami session new cc-auth
# 注入环境后启动交互式 claude，并把任务文件作为初始 prompt 带入
roami session send cc-auth "claude \"\$(cat ~/.roami/cc-swarm/tasks/auth.md)\""
```

`claude "<prompt>"` 会启动交互式会话并把 `<prompt>` 作为第一条消息。
`roami session send` 末尾自带回车，会话随即开始干活。

> 如果项目需要在特定目录运行，先在任务文件里或命令里 `cd`：
> `roami session send cc-auth "cd /path/to/repo && claude \"\$(cat ...auth.md)\""`

### Step 3: 确认启动成功

```bash
sleep 8
roami session capture cc-auth --lines 40
```

确认 claude 已经起来并开始处理任务（看到它在读文件/规划），而不是卡在 shell 或报错。

### Step 4: 记账

- 调用 `_group_add` 思路：在蜂群记忆为该会话建记忆文件（见 memory.md），记录它对应哪个子任务、起始时间、初始指令。
- 更新 `_tasks.md`，把该子任务标记为「已派发 → cc-auth」。

## 按依赖顺序与并发上限分批开

**不要一次把所有会话全开起来** —— 会撞 429（见 concurrency.md）。

```
读 _tasks.md 的依赖图
  ↓
第一批：开「无依赖」的子任务，且数量 ≤ 并发上限（2-3 个）
  ↓
巡检它们；当上游产出 API 契约 / 完成 / 空出并发位
  ↓
第二批：开被解锁的下游子任务
  ↓
... 直到所有子任务都派发完
```

开每个会话之间间隔 20-30 秒，别同一秒触发多个 claude 冷启动。

## 无人值守方式（备选）

适合一批可信、独立、跑完即弃的小任务。一条命令开一组：

```bash
roami session agent spawn fix \
  "typo"   "修正 README 里的错别字并 commit" \
  "lint"   "跑 npm run lint --fix 并提交" \
  --dir /path/to/repo --model sonnet

roami session agent status fix          # 看进度
roami session agent send fix-typo "顺便检查 CONTRIBUTING.md"   # 追加
roami session agent collect fix --json  # 跑完收集结果
roami session agent kill fix            # 清理
```

这些会话用 `claude -p --dangerously-skip-permissions`，**不弹审批、不需要巡检**，
跑完自动退出。cc-swarm 只需在集成阶段 `collect` 它们的产出。

## 关联看板卡 + 告诉成员怎么协作

开完成员会话后，把它对应的看板卡派给它，并在给成员的**任务 prompt 里**写明协作纪律：

```bash
roami session swarm task assign <群> <卡id> <成员>      # 把卡派给刚开的成员（自动进 assigned）
```

给成员的任务文件末尾加一段（让成员主动用广场/看板，而不是等你来抓屏）：

```markdown
## 协作约定（本蜂群）
- 认领：开工前 `roami session swarm task move <群> <你的卡> doing`。
- 播报：有产出/契约就 `roami session swarm say <群> --kind done "<一句话+契约>"`（会自动署名你）。
- 卡住：缺东西就 `roami session swarm say <群> --kind block "<缺什么>"`，别干等。
- 提问：`roami session swarm say <群> --kind ask "<问题>"`，我会在广场回你。
- 交付：做完 `roami session swarm task move <群> <你的卡> review`，等我审。
```

> 成员**不自己派活**、不替别人决策；只推进自己名下的卡 + 在广场喊话。派活权只在 master。

## 派活后

会话开起来后，cc-swarm 的角色从「包工头」切到「监护人」，进入 patrol.md 的持续巡检循环。
