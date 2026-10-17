# 看板（Board）· 任务卡详解

每个蜂群一份**看板**：把要做的事拆成**卡片**，谁负责什么、卡在哪一目了然。全群共享，落在 `swarm.db`。
**分工是单中心的——只有 leader 派活**；成员只推进自己名下的卡。

## 列（column）

卡片在这几列之间流转：

| 列 | 含义 |
|------|------|
| `backlog` | 待办（新建默认落这里） |
| `assigned` | 已派给某成员、待开工 |
| `doing` | 进行中 |
| `review` | 待审 / 验收中 |
| `done` | 已完成 |
| `blocked` | 被阻塞 |

## 命令：`roami session swarm task <子命令>`

```bash
# leader：建卡（返回卡 id 如 t1）
roami session swarm task add <群> "<标题>" [--desc "<细节>"] [--assignee <成员>] [--deps t1,t2] [--col <列>]

# leader：把卡派给成员
roami session swarm task assign <群> <卡id> <成员>

# 看板全貌 / 我的卡
roami session swarm task ls <群> [--col <列>] [--assignee <成员>] [--json]
roami session swarm task show <群> <卡id>

# 成员：流转自己名下的卡
roami session swarm task move <群> <卡id> <列>     # 如 move t3 doing / review
roami session swarm task done <群> <卡id>          # = move 到 done

# leader：删卡
roami session swarm task rm <群> <卡id>
```

`--deps t1,t2`：表达卡之间的先后关系（画依赖、供参考）；它**不挂起成员**（成员仍立即开工，软依赖靠广场协调）。

## 谁动哪张卡

- **leader**：`add` 拆活上板、`assign` 派活；据看板调度。
- **成员**：只 `move` / `done` **自己名下**的卡（开工→`doing`，待审→`review`，完成→`done`）；**不替别人派活、不动别人的卡**。
- 看板 = 分工底账，广场 = 沟通；两者配合：完成一张卡时，在广场 `swarm say --kind done --re <卡>` 播报一声。

## 典型流

1. leader：`t1=$(roami session swarm task add 群 "认证后端" --desc "注册/登录/JWT" --assignee api)`。
2. api 成员：开工 `task move 群 t1 doing` → 完成 `task done 群 t1` + `swarm say 群 --kind done --re t1 "接口已就绪"`。
3. leader 巡检 `task ls 群` 看全貌，审完推进 / 派下游。
