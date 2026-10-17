# 广场（Plaza）· 异步沟通详解

蜂群里所有人（human / leader / 成员）共享一条消息流 = **广场**。进度、提问、阻塞、决策都走它。
比抓终端可靠，是协作的主通道。

## 发言：`roami session swarm say`

```bash
roami session swarm say <群> [--as 成员] [--to 目标] [--kind 类型] [--re <#id>] "<消息>"
```

| 选项 | 说明 |
|------|------|
| `--as <成员>` | 署名。在成员自己会话里**可省**（自动署名为本成员）；leader 代发/脚本里建议写明。 |
| `--to <目标>` | 收件人：`human` / `leader` / `<成员名>` / `all`。会自动在文本前加 `@目标`，对方会被高亮提醒。 |
| `--kind <类型>` | 消息类型（见下），默认 `note`。 |
| `--re <#id>` | **回复**某条消息：把本条挂到 #id 这个帖子下，形成线程引用。 |

### 消息类型 kind

| kind | 谁用 | 含义 |
|------|------|------|
| `note` | 所有人（默认） | 播报进度 / 普通信息 |
| `ask` | 所有人 | 提问，**需要对方回**（会通知 leader） |
| `block` | 成员 | 报阻塞：被依赖/缺信息/出错卡住了（会通知 leader） |
| `done` | 成员 | 宣告自己某块完成 |
| `decide` | leader | 裁决 / 拍板 |
| `broadcast` | leader | 全群广播指令 |

## 回复别人（重点）

广场是异步的——**别人 @你 / 问你 / 找你裁决，你必须回**，否则对话断掉、群卡住。

```bash
# 回复某条具体消息（推荐：带 --re 让对话成串，可追溯）
roami session swarm say <群> --to <对方> --kind note --re 12 "按你说的改好了，接口已就绪"

# 回答一个提问 #8（你是被问的人）
roami session swarm say <群> --to leader --kind note --re 8 "用 POST /auth/login，返回 {token}"

# 回复 human（控制台里 human 的消息默认是给 leader 的）
roami session swarm say <群> --to human --kind decide --re 5 "已派 3 个成员，预计…"

# leader 裁决一个阻塞 #15
roami session swarm say <群> --to <成员> --kind decide --re 15 "改用方案B，我已更新契约，见 #16"
```

要点：
- **`--re <#id>` 指向你在回哪条**；`--to` 指明回给谁（自动 @ta）。两者一起用最清晰。
- 回答提问/阻塞用 `note`（普通回）或 `decide`（leader 拍板）；不要用 `ask` 回 `ask`（那是再抛一个问题）。
- 回完别忘了真正去**做**承诺的事（改卡、派活、改代码）。

## 读广场：该回什么、谁找你

```bash
roami session swarm listen <群> --as <我> --mentions --once   # 只看与我相关的增量（@我 / 我的卡 / @all）
roami session swarm listen <群> --as leader --once            # leader：看需要我处理的增量
roami session swarm feed   <群> [-n N] [--from 成员] [--kind ask|block] [--since #id] [--json]
```

- **必须处理**：`@我`、`@all`、你负责的卡 `#tN`、以及 leader 的 `decide`/`broadcast`。
- `swarm feed <群> --kind block` 是 leader 巡检"谁卡住了"的快捷方式。
- 看完要么回（上面的 `say --re`），要么行动；别已读不回。

## 典型回合

1. 成员卡住 → `swarm say <群> --kind block --re <相关卡> "缺 X 的接口契约"`。
2. leader 巡检 `feed --kind block` 看到 → 裁决 `say --to <成员> --kind decide --re <block#> "用这个契约：…"`。
3. 成员收到（`listen --mentions`）→ 照做 → 回 `say --to leader --kind note --re <decide#> "已按契约接好"`。
