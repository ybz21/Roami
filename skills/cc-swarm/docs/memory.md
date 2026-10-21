# Session 记忆 (memory)

cc-swarm 为每个被管理的 session 维护一个记忆文件，持久化跨巡检轮次的上下文。

## 存储位置

```
~/.roami/cc-swarm/
  cc-oauth.md
  cc-回测.md
  cc-数据.md
  ...
```

目录在首次巡检时自动创建。

## 记忆文件格式

每个 session 一个 markdown 文件，结构固定：

```markdown
# cc-xxx

## 任务
> 一句话描述这个 session 在做什么

## 阶段
coding | testing | reviewing | fixing | done

## 时间线
- [HH:MM] 开始：xxx 功能开发
- [HH:MM] 完成开发，idle
- [HH:MM] cc-swarm: 发送测试指令 — "写 pytest 覆盖..."
- [HH:MM] 测试完成，7 case 全过
- [HH:MM] cc-swarm: 发送架构 challenge — 3个问题（fallback重复/限流硬编码/能力矩阵）
- [HH:MM] 修正中...
- [HH:MM] 修正完成

## 产出
- backend/services/xxx.py — 核心服务
- backend/tests/test_xxx.py — 7 个测试用例
- backend/routers/xxx.py — API 端点

## Review 发现
1. [已修] Fallback 链重复实现 → 抽了 FallbackChain 类
2. [待修] 限流器不支持付费额度
3. [已修] free tier 能力判断分散

## 待办
- [ ] 限流器改为从配置读取
- [x] 写测试
- [x] 架构 review

## 备注
- 它在 PR #4 分支上
- 依赖 tickflow>=0.1.22
```

## 读写时机

### 写入（更新记忆）

每轮巡检后，对发生变化的 session 更新记忆：

| 事件 | 更新内容 |
|------|---------|
| 首次发现 session | 创建文件，从 capture 推断任务描述 |
| 发送了指令 | 时间线追加，记录发了什么 |
| session 完成了一个阶段 | 更新阶段、时间线 |
| review 发现问题 | 写入 Review 发现 |
| session 修复了问题 | 更新 Review 发现状态 |
| session 产出了文件 | 更新产出列表 |

### 读取（辅助决策）

巡检时，在 capture 之外**先读记忆文件**，获取：

- 上一轮发了什么指令？→ 避免重复发
- 当前处于什么阶段？→ 决定下一步做什么
- review 有哪些问题还没修？→ 跟进
- 这个 session 做了多久了？→ 判断是否卡住

```
决策流程：
  读记忆 → 读 capture → 结合两者判断 → 执行决策 → 更新记忆
```

## 阶段流转

```
coding → testing → reviewing → fixing → done
  ↑                               │
  └───────────────────────────────┘  (review 发现新问题)
```

| 阶段 | 含义 | cc-swarm 行为 |
|------|------|------------|
| coding | 正在开发功能 | 审批，不干预 |
| testing | 在写/跑测试 | 审批，等结果 |
| reviewing | cc-swarm 在 review 它的代码 | 发 challenge |
| fixing | 在修 review 发现的问题 | 审批，等完成 |
| done | 全部完成 | 不再发指令 |

## 记忆卫生

- **不要让记忆文件无限增长** — 时间线超过 20 条时，压缩早期条目
- **session 被 kill 后** — 记忆文件保留（有历史价值），但标记阶段为 done
- **新对话启动 cc-swarm** — 读取已有记忆文件，恢复上下文
- **记忆和 capture 冲突时** — 以 capture（实际状态）为准，更新记忆
