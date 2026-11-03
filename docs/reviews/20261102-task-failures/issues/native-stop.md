# fix(agent): 已确认工具停止的 native 异常仍被误标为 interrupted

## 复现路径

在 hold_workspace 内抛出 OSError/ValueError，且 stopped() 返回 True。当前 except BaseException 先把 confirmed=False，finally 使用 confirmed and await stopped() 短路，停止证据永远不读取，抛 NATIVE_WORKSPACE_OUTCOME_UNKNOWN。

## 影响与证据

普通已停止失败错误进入 unknown/interrupted，阻塞安全续作；节点历史有 2 次此 summary，但旧记录无原因链，不能断言两次均来自此 bug。

代码（排查基线 08ad956b）：`agent-runtime/src/roami_agent/executors/workspace.py:97-104`。

## 建议修复与验收

读取停止证据；对普通异常允许确认已停止，对明确未知副作用继续保持 unknown。保留异常链，并覆盖停止真/假、未知 DomainError 和取消测试。

## 去重

已搜索仓库全部 49 个现有 issue；#350 覆盖旧执行限制，#398 覆盖旧未知任务恢复，当前缺陷范围与两者不同。保留历史未知写入保护，不重放历史任务。

## 补充历史取证

两条历史包裹错误的 turn.failed 都是 TOOL_OUTCOME_UNKNOWN，且分别有 browser_open unknown / browser_act unknown。本 issue 的误判由普通异常 + stopped=True 反例确认，不把这两条历史任务计为已证实误判，也不会重放它们。
