---
name: dev-roles
description: >
  软件开发的角色分工指南：一个开发任务/项目该拆成哪几个角色（产品/架构/前端/后端/
  全栈/测试/设计/审查/运维/文档），每个角色的 scope（负责什么、产出什么、边界在哪），
  以及按项目规模怎么选角色、角色之间怎么协作。每个角色另有详细子文档 docs/<key>.md。
  Roami Main 拆分成员职责和验收标准时读它；也可单独规划团队分工。
user-invocable: true
allowed-tools:
  - Read
---

# /dev-roles — 软件开发角色分工与 scope

把一个开发目标拆成「一支班子」时对号入座，每个角色有清晰 scope（负责什么 / 产出什么 / 不做什么），
彼此靠**接口契约**解耦以便并行。每个角色的详细打法见 `docs/<key>.md` 子文档。

## 〇、协作底座

Main 使用 `swarm_plan` 把角色职责写进成员 goal 和 acceptance，executor 指定实际执行器。成员使用 `swarm_post` 讨论契约、进展和阻塞，通过 `swarm_status` 查看依赖。结果走原任务 report 与独立验收，返工使用 `task_steer` 继续原任务；只有宿主验证成功才能解锁下游。

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
3. **frontend / backend** 按契约**并行**实现；缺契约先 mock 或 向 Main 提问。
4. **qa** 按验收标准测（`chrome` 真跑）；**reviewer** 做架构级 review。
5. 集成验收，对照 pm 的验收标准逐条确认。

## 四、在蜂群里落地

Main 把角色名称、职责、产物和验收标准写入 `swarm_plan.items`。例如架构成员先冻结 API 契约，前后端依赖其指定 task revision，最终验收成员设置 `integration: true`。依赖是执行门禁，指定版本验证成功前不会启动下游。

成员讨论用 `swarm_post`，不能自行改卡片状态或手工标记完成。完整流程见 `cc-swarm` skill；CLI 计划入口为 `roami swarm plan <sw-id> --file plan.json`。
