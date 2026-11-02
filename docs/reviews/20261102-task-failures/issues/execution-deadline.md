# fix(execution): 区分执行 deadline 与上下文中断并保留部分输出

## 复现路径

运行一个超出显式 TimeoutSeconds 的一次性 CLI，以及一个被父 context cancel 的 CLI，两者均回报 EXECUTION_DEADLINE_OR_INTERRUPTION。

## 影响与证据

节点历史 5 次、目标项目 4 次混合码，无法区分预算到期和进程中断。AGENT_STEP_LIMIT 8 次为历史，当前移除工作关联 #350。

代码（排查基线 08ad956b）：`internal/agentexecution/execution.go:449-458; internal/agentexecution/structured-process.go:124-132`。

## 建议修复与验收

基于 context.Err 返回 EXECUTION_DEADLINE 或 EXECUTION_INTERRUPTED；显式 cancel.json 保持 cancelled；标准与 structured 执行器均测试并保留 stdout/stderr。

## 去重

已搜索仓库全部 49 个现有 issue；#350 覆盖旧执行限制，#398 覆盖旧未知任务恢复，当前缺陷范围与两者不同。保留历史未知写入保护，不重放历史任务。
