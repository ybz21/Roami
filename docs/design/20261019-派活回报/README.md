# 原工作会话的派活回报

2026-10-19：主对话把 PR 任务投递到旧 Codex 后，执行器完成但 Main 只知道 delivered。新增回报关联，补齐原设计中旧会话直接投递的回程，不重启工作会话或修改供应商 Hook 信任。

## 路径与边界

1. Main 使用已有 `session_send` CLI 能力，或 `delegate(target.kind=session)` 的同一路径；七个常驻工具保持不变。
2. Python 在单 writer 事务内登记派活 ID、owner、原对话/分支/用户消息、目标会话和幂等键，附上实例环境固定的 `roami agent reply` 命令后，交既有 Go `execution send-message` 提交。原文与回报命令作为同一次 tmux 提交，未知写操作不重投。
3. Codex / Claude 等执行器按提示词，在返回前写结果文件并执行 CLI。`progress` 为进展，`blocked` 可携 2–4 个选择项，`completed` / `failed` 为终态；每次报告使用稳定 key，重复报告复用原回执，内容冲突报错。
4. CLI 经已有私有 Unix Socket 回 Python。回报不能自选 owner / 对话 / 分支；服务按派活登记还原来源。消息、事件、通知 outbox、报告回执在同一事务提交；得到 messageId / eventId 才表示 Main 已落盘，不代表设备系统推送送达。
5. 复用 Main 历史、SSE、未读和通知策略，浏览器不需保持在后台会话。报告直接展示，不等待 Main 模型二次改写。下一轮 Main 上下文携原目标、状态及外部证据标识。阻塞选项回复携带原会话和派活 ID，供 Main 继续原工作会话。
6. `session_dispatch_status {dispatchId}` 属于 CLI 目录，按原 owner / 对话查询投递状态和最近五份回报。没有报告就是 unconfirmed；供应商生命周期仍未被证明，executionTracked=false。所有报告 verified=false，不自动完成受跟踪任务的独立验收。

命令示例（真实实例会带完整路径环境，ID 由宿主产生）：

```bash
roami agent reply --dispatch DISPATCH_ID --file RESULT.json
```

```json
{"key":"final","status":"completed","summary":"实际交付链接、检查结果及限制"}
```

回报失败保留结果文件，以同一 JSON / 同一 key 重试；不因回报失败重新执行任务。JSON 不允许覆盖来源，阻塞选项去重并校验数量。正式环境依旧只有 Go 一处用户鉴权，内部端点不公开；本机同一 OS 用户通过私有 Socket 调用。回报来源是本机可信调用，不声称供应商签名或防御同 OS 用户的恶意伪造。

## 持久化与兼容

Go 备份恢复兼容上限同步为 8，Python schema 8 新增 `session_dispatches` 和 `session_dispatch_reports`，原对话、任务与历史不改写。派活命令随记录保存，重试使用同一载荷；已知投递拒绝保存 failed，超时或无回执保存 unknown。重启后待回报记录和去重仍有效；不根据终端静止、进程退出、截止时间猜测任务成功。报告记录 sourceMessageIds，忘记原来源后不再注入结果，既有遗忘依赖链可排除已回报内容。

**兼容旧执行器的方法是协作式 CLI 回报，不是自动解析其终端。** 不遵守回报命令、执行器崩溃或始终不可达时，仍可能没有报告；此时保持未确认。已有受跟踪任务继续使用 report / lifecycle / 验收协议。本轮不增加跨节点可靠传输或供应商全局 Hook，不把通知 outbox 等同于设备已读。

此前那次 PR 派活没有新登记，已沿精确源工具记录将结果用现有 notify 人工补回原 Main；不是伪造旧任务的自动完成证据。

## 验证

- Python 领域 / HTTP 用例覆盖关联投递、未知不重投、已知失败、并发去重、冲突、错误 owner / 路由注入、进展与选择题、终态锁定、遗忘阻断、数据库关闭重开恢复及实例路径引用。
- 前端覆盖报告状态、未知不显示为成功、独立验收说明、选择题带目标回复，以及旧消息兼容。
- 端到端采用可控流式供应商和隔离 tmux 执行器；实际经过主对话工具网关、Go CLI、paste-buffer / Enter、Unix Socket、SQLite、SSE 和前端。桌面与 Redmi Note 8 同时先看到进展，再收到结果；执行器重复调用实际 CLI 只有一份结果，刷新后历史仍可读，文档无横向溢出。
- 这不是供应商真实 Codex / Claude 的模型遵循率或 Hook 信任验收，不向生产专业会话发测试消息。旧 PR 结果补回属于用户授权的真实通信，和隔离测试分开记录。
- 运行证据见 [verification.json](verification.json)，PR 附桌面 / Android 改前改后截图；运行日志、凭据和临时数据库不提交。

## 设计修订与验收记录

[按日期查看记录](records/README.md)。
