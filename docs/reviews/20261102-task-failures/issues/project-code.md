# fix(agent): 项目创建 CLI 的非 PROJECT 前缀错误被吞为通用错误

## 复现路径

project create 返回非零退出及 JSON error.code=INVALID_PROJECT_PROVISION / CLI_ERROR 或其他合法公开码；provision_project 只接受 PROJECT_ 前缀。

## 影响与证据

PROJECT_PROVISION_UNAVAILABLE 1 次；历史原码未留存，不能确认其具体来源。代码可复现地丢失请求、连接或目录等 actionable 原因。

代码（排查基线 08ad956b）：`agent-runtime/src/roami_agent/executors/project.py:47-52`。

## 建议修复与验收

沿用 public_error_code 语法校验保留合法结构化码，拒绝含 URL/私密诊断的不合法码；添加 CLI 边界测试。

## 去重

已搜索仓库全部 49 个现有 issue；#350 覆盖旧执行限制，#398 覆盖旧未知任务恢复，当前缺陷范围与两者不同。保留历史未知写入保护，不重放历史任务。
