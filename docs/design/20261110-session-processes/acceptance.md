# 验收记录

2026-11-10，本地分支 `feat/session-process-manager`。

## 自动验证

- 仓库 `scripts/dev/quality/check.sh quick` / `full` 通过，Python 运行时与 Skill 套件按变更范围跳过。
- Go 测试覆盖进程 stat 的括号名称、启动时间、跨隔离组拒绝、主进程保护、普通结束与安全失败。
- Darwin arm64 的 memguard 包交叉构建通过；非 Linux 不提供无法验证安全边界的结束操作。
- 前端类型、双语文案、hover、全量 Vitest（218 个文件、1583 个用例）和生产构建通过。新增测试覆盖进程树、父进程退出与循环快照、确认后才提交、根进程保护、读失败时禁用操作与卸载清理。

## 真实 API / CLI

使用 `scripts/dev/isolated-roami.sh /tmp/roami-processes-validation`，只在私有 tmux 服务里创建测试会话。

- GET 返回 bash 根进程、sleep 子进程、父 PID、RSS、交换区与启动时间。
- POST 结束根进程返回 `SESSION_PROCESS_PROTECTED`；旧启动时间返回 `SESSION_PROCESS_STALE`。
- SIGTERM 后子进程退出，列表自动更新。
- 暂停测试会话后，强制结束子进程成功，根进程保留，之后可继续会话。

## UI

- 桌面在 1280 / 1920 / 2560 / 3440 CSS px 验证 Drawer 打开和关闭、列表边界及文档无横向溢出。面板宽 960px，内容使用剩余高度（900px 视口内为 843px）。
- 桌面真实点击结束与确认后，后端进程退出，列表行数下降。
- Redmi Note 8通过 LAN HTTPS 验证同一个实际组件。手机为 392 CSS px、compact/coarse；返回栏、单一滚动容器和 44px 结束按钮通过。
- ADB 真触控结束进程、确认、返回均通过；滚动使 scrollTop 从 0 变为约 490px；文档 scrollWidth=392，不横向溢出。
- 结束确认期间另一个客户端已结束同一进程时，真机得到过期提示，刷新后可重新选择。
- 组件操作验收使用临时独立入口连接真实隔离 API，入口已清理。主会话页面桌面工具栏和手机更多菜单均接入；整个终端页面的端到端截图未作为本次组件验收依据（测试 Chrome / 终端页导航遇到环境阻塞）。

本机证据（不提交一次性图片进主分支）：

- `/tmp/roami-processes-desktop.png`
- `/tmp/roami-processes-mobile.png`
- `/tmp/roami-processes-desktop-stop-final.log`
- `/tmp/roami-processes-quality.log`、`/tmp/roami-processes-quality-full.log`
- `/tmp/roami-processes-go-final.log`、`/tmp/roami-processes-vitest-final.log`、`/tmp/roami-processes-build-final.log`
