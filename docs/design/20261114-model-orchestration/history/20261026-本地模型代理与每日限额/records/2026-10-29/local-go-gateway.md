# 本地 Go 模型网关验收 · 2026-10-29

[设计与使用](../../README.md)

## 自动回归

- Go 网关测试覆盖导入的价格规则、最长前缀、精确小额计算、缓存分项、价格快照、幂等结算、并发准入、时区账期、重启恢复、未知费用核账、零默认价格、SSE 任意分块与非法用量、HTTP 失败和重定向、socket 权限与单实例锁。
- `go test -race ./internal/modelgateway ./backend/agentproxy` 通过，包括已认证 API 选择 Go socket、保持查询参数并移除浏览器凭据。
- Python 新增 8 项测试：main/worker/memory 都走私有 socket、本地限额和未知费用拒绝不重试、网关缺失不绕过计费、容器桥接保留专用 transport。
- 真实 Go CLI / Python runtime 集成测试增加本地账目断言；就绪检测改为 Agent status，避免把网关 socket 当作 Agent 启动完成。上述集成与 transport 测试合计 9 项通过。

`scripts/dev/quality/check.sh full` 通过：Go 全量、Python lint/format 与 1842 项测试（14 项跳过）、前端 typecheck/i18n/hover/生产构建、密钥与文件策略检查。收尾新增的在途请求错误映射及统计完整性调整，另以 9 项 Python 专项回归和 Go 网关/代理/服务/CLI 四个包的 race 测试通过。全量日志位于 `/tmp/roami-local-gateway-20261029/quality-full.log`。

## 隔离实例实测

使用 `scripts/dev/isolated-roami.sh /tmp/roami-local-gateway-20261029/instance6 ...` 启动开发实例，私有 tmux server 与用户会话分离。Go 二进制由当前工作区构建，通过实际 `roami agent serve` 启动 Python；上游为本地 HTTP/SSE 夹具，没有付费模型调用。

1. 通过 `roami agent gateway configure` 配置每日 2 CNY，主对话生成真实流式回复，账本结算 2.000000000 CNY。
2. 再次发送被本地 `MODEL_PROXY_DAILY_LIMIT` 拒绝，上游请求数仍为 1。
3. 重启 Go / Python，价格、限额和已知消费保留。
4. 将限额改为 5 CNY，上游故意省略 usage，账目保留 unknown；下一次发送以 `MODEL_PROXY_USAGE_UNKNOWN` 拒绝，上游仍只有 2 次请求。
5. 通过 CLI 将未知费用核对为 0.75 CNY，已结算总额为 2.75 CNY。
6. 再发送成功；该轮触发的 Worker 调用也进入同一账本。最终上游 4 次请求，主连接 4.75 CNY、Worker 2 CNY，总计 6.750000000 CNY。最后一笔开始前低于 5 CNY，因此允许完成并超额，符合请求前准入语义。

停止 Agent 后执行统一 `roami db backup`，再恢复到另一个隔离目录：catalog 保留 `model-gateway`，账目总额仍为 6.750000000 CNY，价格与每日限额 5 CNY 均保留。

实测日志：`/tmp/roami-local-gateway-20261029/smoke.log`；完整分组与最近调用：`/tmp/roami-local-gateway-20261029/usage.json`。实例已停止，统一隔离入口负责关闭其专用 tmux server。

未部署或重启用户现用服务。此修订提供后端和 CLI；不声明新增 Web 计费画面或手机交互验收。
