# 会话 CLI 与测试清理隔离

2026-10-21，针对测试清理误停主 tmux server 的修复。

## 事故与边界

测试启动进程清除了继承的 `TMUX`，但临时清理命令没有复用同一环境。清理只改 `TMUX_TMPDIR`，实际仍连接 `TMUX` 指向的主 socket，停止了其下全部会话。命令名称迁移不能解决原生 tmux 的目标选择。

本次同时收敛公共入口与测试资源归属。原生 tmux 保留为会话底座；同一用户拥有任意 shell 时仍能直接访问该用户的 socket。本次不引入独立 OS 用户、容器或会话代理鉴权，不能视为权限沙箱。

## 公共 CLI

- 统一使用 `roami session`，退役 `ttmux` 可执行名和 `roami ttmux` 别名；旧名即使重新创建软链也会被新程序拒绝，包括 `server` 模式。
- 未知命令在观察 tmux 前报错，不再原样转发；移除公共全局关闭和原生配置加载入口。
- 新建会话仅接受明确业务参数，窗口和窗格命令不再接受任意原生参数。
- 关闭会话必须提供一个明确目标，重复展示名报错；交互菜单先让用户选择目标，再调用同一业务路径。
- `roami session keys` 提供明确目标的按键白名单，与 HTTP 共用校验；技能不再直接调用原生按键命令。
- 后端必要的 `list-sessions`、`list-panes`、`display-message`、`send-keys` 通过内部适配器调用；配置外部 Roami 程序时，业务调用显式添加 `session` 子命令。

## 测试实例

`scripts/dev/isolated-roami.sh <测试目录> <命令...>` 固定全部存储根，并初始化记录在 `tmux-instance.json` 的独立 server。实例使用由规范化目录散列得到的私有 socket，记录 PID 和随机实例标记；tmux 不加载用户配置。

应用的 `TMUX_BIN` 固定为该 socket 的包装器，原生测试子进程也继承私有 `TMUX`。`TMUX_TMPDIR` 使用短私有路径，避免子测试自选 `-L` 名称时超过 Unix socket 路径长度限制。

同一入口的 `--verify` 检查记录与实际 server，`--stop` 校验后只停止该 server，重复停止安全。记录的目录、socket、PID 或 server 标记不匹配时拒绝访问。`agent-acceptance/instance.py` 的初始化、服务启动和清理共用此入口；服务进程还核对存储根与进程组归属，启动失败也清理测试实例。

`--stop` 只管理记录的 tmux server，普通命令自行后台启动的其他进程需要由其拥有者管理；完整 Web/Agent 验收使用 `agent-acceptance/instance.py` 的启停接口。

## 安装与兼容

旧链接、旧 Bash 实现、旧辅助脚本和旧技能归档到配置备份根下的 `cli-entry-migration/`，移出 PATH 与技能发现目录。新技能名为 `roami-session`，补全统一为 Roami；发布不再生成 `ttmux-*` 资产。

会话 ID、数据库、旧路径读取、`TTMUX_*` 环境兼容、`_ttmux-*` 基础设施标识及内部包名保留。本次不迁移持久身份，也不重建用户会话。

CLI 输出属于国际化规范中的“用户 shell 里的终端输出”例外；本次未添加前端产品文案或改变 Web 布局。

## 验证

- `internal/cli/command-boundary_test.go`：未知及全局停止命令不触发 tmux。
- `cmd/roami/isolation_test.go`：两个独立测试 server，继承另一 socket 的环境启动测试实例；篡改记录被拒绝，停止测试实例后另一 server 的会话仍在。
- `internal/session/close-target_test.go`：缺少或多个关闭目标时不观察 tmux。
- `tests/test-session-cli.sh`：真实创建、派生、改名、输入提交、读取、明确目标关闭；拒绝原生命令、全局停止和同名歧义。
- `scripts/dev/selftest/retired-session-entries.sh`：旧入口归档、新技能安装与重复迁移。
- 完整验收实例实际启动 Web、Python Agent 和 tmux 后，用同一记录清理；核对用户原有会话 pane PID 保持不变。
- `scripts/dev/quality/check.sh full` 在独立实例中执行；新脚本另通过 Ruff 检查。
