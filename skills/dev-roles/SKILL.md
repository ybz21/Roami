---
name: dev-roles
description: >
  软件开发的角色分工指南：一个开发任务/项目该拆成哪几个角色（产品/架构/前端/后端/
  全栈/测试/设计/审查/运维/文档），每个角色的 scope（负责什么、产出什么、边界在哪），
  以及按项目规模怎么选角色、角色之间怎么协作。每个角色另有详细子文档 docs/<key>.md。
  蜂群(swarm) leader 拆班子、给成员定 `--subrole`/`--duty` 时读它；也可单独规划团队分工。
user-invocable: true
allowed-tools:
  - Read
---

# /dev-roles — 软件开发角色分工与 scope

把一个开发目标拆成「一支班子」时对号入座，每个角色有清晰 scope（负责什么 / 产出什么 / 不做什么），
彼此靠**接口契约**解耦以便并行。每个角色的详细打法见 `docs/<key>.md` 子文档。

## 〇、协作底座（所有角色通用，先会这个）

不管你是哪个角色，在蜂群里都**靠这三样协作**，动手前先记牢：

### 广场（异步沟通，最常用）

```bash
roami session swarm say <群> --as <我> --kind note|ask|block "<消息>"   # 播报进度 / 提问 / 报阻塞（自动署名）
roami session swarm listen <群> --as <我> --mentions --once             # 拉与我相关的增量消息
roami session swarm feed <群>                                           # 看整条消息流
```
- **必处理**：`@我`、`@all`、你负责的卡 `#tN`、以及 leader 的 `decide`/`broadcast`。
- 需要全局调度/别人的活 → `--to leader --kind ask`，**不要自己替别人派活**。

### 看板（分工，谁负责什么一目了然）

```bash
roami session swarm task ls|show|move|done <群> …    # 看 / 认领 / 流转你名下的卡
```
- 卡 = "要做的事"；你只推进**自己名下**的卡（`move` 到 doing/review，完成 `done`）。

### chrome（CLI · Web 验收）

```bash
roami chrome goto|click|fill|text|eval|screenshot|tabs …   # 用法: roami chrome help
```
- Web 类成果**用 chrome 真跑一遍**（开页面、点按钮、断言文本），比只读代码可靠。
- **干完务必**（解锁下游）：`roami session swarm done <群> <我>`。

> 以上是速记。**详细说明各一篇**：[docs/plaza.md](docs/plaza.md)（广场，含**怎么回复** `--re`/`--to`/kind）、
> [docs/board.md](docs/board.md)（看板，列与卡片流转）、[docs/chrome.md](docs/chrome.md)（chrome CLI 全部命令+验收套路）。
> 各角色子文档只讲该角色**特有**的 scope 与打法，不再重复这一节。

## 一、角色清单（key 即 `--subrole` 取值）

| key | 角色 | scope 一句话 | 子文档 |
|-----|------|------|------|
| `pm` | 产品经理 | 把目标变成清晰、可验收的需求 | [docs/pm.md](docs/pm.md) |
| `architect` | 架构师 | 定技术方案、接口契约、数据结构、分层 | [docs/architect.md](docs/architect.md) |
| `frontend` | 前端工程师 | 按契约实现 UI 与交互 | [docs/frontend.md](docs/frontend.md) |
| `backend` | 后端工程师 | 实现服务 / API / 数据层 | [docs/backend.md](docs/backend.md) |
| `fullstack` | 全栈工程师 | 端到端打通一条链路 | [docs/fullstack.md](docs/fullstack.md) |
| `qa` | 测试工程师 | 按验收标准测正常/边界/异常 | [docs/qa.md](docs/qa.md) |
| `designer` | 设计师 | 视觉 / 交互规范与标注 | [docs/designer.md](docs/designer.md) |
| `reviewer` | 代码审查 | 架构级 review、提 challenge、把关风险 | [docs/reviewer.md](docs/reviewer.md) |
| `devops` | 运维 | 构建 / 部署 / CI / 运行环境 | [docs/devops.md](docs/devops.md) |
| `docs` | 文档 | 面向读者的使用/设计文档 | [docs/docs.md](docs/docs.md) |

> 表外角色（如 `data`/数据、`security`/安全）按需自定义：`--subrole` 直接写字符串，走通用处理。

## 二、按规模选角色（别为拆而拆）

| 项目 | 建议班子 |
|------|------|
| 单文件 / 脚本 / 小工具 | **1 个 fullstack**（或不分角色，直接做） |
| 一个完整功能（前后端） | architect（定契约）+ frontend + backend + qa（产品/设计可选） |
| 纯前端 / 可视化 / 页面 | designer（可选）+ frontend（+少量 data/backend） |
| 大型 / 多模块 | 全套 + reviewer + devops + docs |

原则：**优先拆出能并行的角色**（前后端靠 architect 的契约解耦）；有先后用软依赖表达（成员仍立即开工，缺上游产出就去广场等/问）。

## 三、协作流（典型顺序）

1. **pm** 把目标写成需求 + 验收标准。
2. **architect** 冻结接口契约/数据结构 → 广场广播（前后端能并行的前提）。
3. **frontend / backend** 按契约**并行**实现；缺契约先 mock 或 `--to architect --kind ask`。
4. **qa** 按验收标准测（`chrome` 真跑）；**reviewer** 做架构级 review。
5. 集成验收，对照 pm 的验收标准逐条确认。

## 四、在蜂群里落地

leader 拆完后，每个角色开一个成员，**务必带 `--subrole` 和 `--duty`**：

```bash
roami session swarm add <群> arch --type agent --subrole architect --duty "定 API 契约与数据结构，冻结后广播"          "<起步任务>"
roami session swarm add <群> api  --type agent --subrole backend   --duty "按契约实现服务与数据层" --depends-on arch  "<起步任务>"
roami session swarm add <群> ui   --type agent --subrole frontend  --duty "按契约实现页面与交互"   --depends-on arch  "<起步任务>"
roami session swarm add <群> qa   --type agent --subrole qa        --duty "端到端验收与回归"       --depends-on api,ui "<起步任务>"
```

`--subrole` 决定该成员拿到的角色化 prompt；`--depends-on` 只表达关系（软依赖：成员立即开工，不挂起）。
完整编排规范见 `cc-swarm` skill 的 decompose / spawn 文档。
