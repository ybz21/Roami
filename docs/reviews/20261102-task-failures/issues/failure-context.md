# fix(agent): 后台执行异常丢失类型与原因链且 deadline 降级为 EXECUTION_FAILED

## 复现路径

让执行器抛 TimeoutError、httpx.HTTPError 或含安全 DomainError 原因链的异常。TaskDispatcher.run 只保留 summary=EXECUTION_FAILED 或外层码。

## 影响与证据

历史 1 次 EXECUTION_FAILED、2 次 NATIVE_WORKSPACE_OUTCOME_UNKNOWN 无法从结果确认原因；outer native deadline 也可能被混为通用错误。

代码（排查基线 08ad956b）：`agent-runtime/src/roami_agent/dispatch/runner.py:221-230`。

## 建议修复与验收

持久化有界且脱敏的 exceptionType / causeCodes，禁止原始消息、URL、凭据；明确区分执行 deadline 并覆盖数据库结果和未知保护。

## 去重

已搜索仓库全部 49 个现有 issue；#350 覆盖旧执行限制，#398 覆盖旧未知任务恢复，当前缺陷范围与两者不同。保留历史未知写入保护，不重放历史任务。
