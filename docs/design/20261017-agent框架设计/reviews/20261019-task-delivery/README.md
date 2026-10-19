# 2026-10-19 任务交付与失败收敛 Benchmark

本套件来自当天生产失败：同一 PPT 请求反复新建任务，错误包括不存在的工作区、native 步数限制、未知写操作、Codex deadline、模型 401；另一个 Codex 设置评审已产出报告，但 UI 打不开报告、继续跳转已退出的会话。

测 Agent 的任务数量、工具副作用、回报链、状态与产物生命周期；不是知识问答。固定错误注入用于可重复回归，不把它记成真实模型通过率。原 [GAIA 风格 / Skill / 记忆 / 多工具链用例](../20261019-e2e-cases/cases.json) 和既有结果保留，本套件增量补齐失败恢复与交付。

- [可浏览的 Benchmark 报告](index.html)
- [设计](../../technical/19-task-delivery.html)
- [30 条具体场景及可执行测试映射](cases.json)
- [本次实际结果](results.json)
- 执行入口：`scripts/dev/agent-acceptance/task_delivery.py`

```bash
python3 scripts/dev/agent-acceptance/task_delivery.py \
  --output /tmp/roami-task-delivery-benchmark.json
```

入口串行运行 Python 的本套件、既有路由 / CodingExecutor / 续接回归，以及 Go 超时证据保留测试和前端任务详情测试。结果逐项记录命令、退出码和耗时，任何一组失败都返回非零；完整日志留在输出 JSON 同目录。默认不访问生产实例、不启动付费模型、不修改主对话、不伪造人工验收。

前端回归另外覆盖：结束任务不打开死会话；运行任务打开准确 sessionId；异步补齐的报告立即支持预览和下载；旧记录中非文本 summary 不导致崩溃。Go 回归检查 deadline 后仍保留部分 stdout 和 stderr，结果继续 failed。

## 人工与真实执行器验收

当前浏览器 / Android 记录在 results.json，早期真实 Codex、Claude Code 小文件交付记录在 results-before-unlimited.json。浏览器验收连接隔离 Go + Python + SQLite，夹具明确标记为示例；检查超链点击预览、下载内容、日志折叠、未知状态、横向溢出。手机使用 Redmi Note 8，通过 LAN HTTPS、实际粗指针和合成触摸滚动验证；不以窄屏截图冒充真机。

真实专业执行器用独立工作目录新建小任务：写 `delivery-proof.md`，读回并返回绝对路径的 Markdown 超链。必须核对文件内容和 ArtifactStore 留存，waiting_user 是“执行器报告成功，等待用户核验”，不是独立验收完成。执行器失败则记录实际原因；不静默更换执行器把失败抹掉。

## 明确限制

- 取消固定失败次数门槛；按未知写入与未修复的鉴权 / 工作区证据阻止重建。相同目标复用已有任务。
- 不清理或合并生产旧失败任务，保留历史证据；不会自动恢复当时已经丢失的完整 stdout 或完整专业对话。
- 报告只保存明确链接、确实存在于绑定工作区的允许格式；缺失、越界、删除和超限如实不可用。普通 Markdown / 文本 / 图片可预览，其他类型可下载；HTML 相对依赖不自动打包。
- 当前运行时仍兼容旧调用缺省 routing；新 Main 使用已有语义路由协议，复杂度不按任务名硬编码。路由评测与文件存在性不能代替专业产物内容质量的人工验收。

## 本轮改动文件

- `agent-runtime/src/roami_agent/dispatch/tasks.py`、`dispatch/task_revisions.py`：同请求防重、失败收敛、预算续接、历史任务产物补齐。
- `agent-runtime/src/roami_agent/storage/task_deliverables.py`、`storage/artifact_store.py`：可信工作区内安全留存、owner 隔离、完整性与删除语义。
- `agent-runtime/src/roami_agent/tools/main_catalog.py`、`executors/professional_brief.py`、`server/configuration.py`、`app.py`：有界失败证据、专业交付简报、独立时限与组装。
- `internal/agentexecution/execution.go`、`execution_test.go`：deadline 后保留有界部分输出与回归。
- `frontend/src/components/agent/AgentTasks.tsx`、`TaskOutput.tsx`、`agent-task-protocol.ts`、`agent-tasks.css`、`agent-tasks.test.tsx`：结束记录、Markdown 超链、产物预览 / 下载、历史兼容；`frontend/src/i18n/locales/{zh-CN,en-US}.ts`：对应文案。
- `agent-runtime/tests/test_task_delivery_benchmark.py`：27 条生产失败回归（按最终持续执行规则修订）；`test_unlimited_execution.py`：3 条调用计数、取消、历史消息回归；`test_routing_policy.py`、`test_conversation_activity.py`：更新配置预算和合法存储夹具。
- `scripts/dev/agent-acceptance/task_delivery.py`：可重复运行的测试入口。
- 本目录 `index.html`、`cases.json`、`results.json`、`README.md`；框架 `technical/19-task-delivery.html`、技术总览与 README；执行器边界的 `implementation.md`：设计、方法、结果与溯源。

早期仓库检查（修改持续执行规则之前）：Go 全量、Python 603 条、前端 710 条、typecheck、i18n 3024 keys、hover、build、secret scan。最终规则与验收见工作台 implementation.md，旧专业执行器实测记录保留在 results-before-unlimited.json。前端构建仍有已有的大 chunk 提示，不是构建失败。没有生产任务 / 连接配置 / 记忆数据写入；当前 worker 连接只做一次只读短请求，凭据未写入代码和报告。

真机复测备注：首轮实际设备预览、触摸滚动、下载命中验证通过；之后再次复测时，同一手机正被另一项任务使用并弹出系统剪贴板权限框，已停止该次复测，没有处理其他任务的授权弹框。保留首轮真实结果，不将受阻的重复检查记为通过。隔离服务已清理，生产 Web / Agent 服务保持原部署版本。
