# 派发任务的自动执行模式

## 产品与用户故事

用户从 Main 把工作交给 Claude Code、Codex、OpenCode 后，新任务应以各执行器的自动模式启动，能够继续执行工具操作。常驻和单次任务使用相同的权限映射。

## 技术设计

此前 `CodingExecutor.run` 没有在启动载荷中传递权限，常驻启动又用空值覆盖了 `DefaultAgentConfig` 的权限默认值；Codex 交互参数忽略权限，OpenCode 通用启动参数也未适配。

- Python 新建会话和项目任务显式传递 `permission=auto`。
- Claude Code 沿用 `--permission-mode auto`。
- Codex 交互和单次执行均映射为 `--dangerously-bypass-approvals-and-sandbox`。
- OpenCode 交互和单次执行均映射为 `--auto`；结构化执行复用注册表参数，继续保留 `--standalone`、JSON 输出和供应商会话 ID。
- 续派已有会话不传权限覆盖；新建的常驻会话保留首轮权限。手动创建的旧会话沿用其已有权限。
- 设置仅作用于子进程启动参数，不修改用户全局配置或模型路由。OpenCode 的显式 deny 仍生效，Claude 的 auto 仍使用供应商自身的自动决策规则。

## 验收

- 本机三种 CLI 的 `--help` 确认对应参数可用。
- Python 定向回归 50 项通过，覆盖三种执行器、会话/项目、常驻/单次，以及续派不覆盖权限。
- Go 注册表与启动命令回归覆盖权限映射、Codex 恢复和 OpenCode prompt 参数顺序；结构化 OpenCode 初轮/续轮均保留自动模式。
- 隔离 tmux 的真实 Python → Go → 常驻子进程测试通过。离线 Claude/Codex 夹具在缺少对应自动模式参数时失败，并验证首轮、手动修改、Main 续派保留对话，明确关闭后才退出。
- 验证使用离线执行器夹具，未调用真实供应商模型服务。
- `scripts/dev/quality/check.sh quick` 通过：Go 全量测试、Python 2146 passed / 21 skipped、Ruff 检查及格式、前端 typecheck / i18n / hover、CLI 与脚本审计均通过。隔离 tmux 测试实例已通过同一启动器清理。
