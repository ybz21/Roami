# 会话进程与内存管理

## Product Design

会话内存统计包括 Agent、编译守护进程和模拟器，用户需要知道具体是谁占内存，并结束不再需要的进程。
桌面会话工具栏增加“进程”，打开右侧详情；手机从会话更多菜单进入全屏二级页。
列表按父子关系缩进，同级按驻留内存排序，展示进程名、PID、父 PID、RSS 与非零交换区占用。
命令和原始进程状态默认折叠。每行提供“结束”和“强制结束”，确认后仅作用于选中进程。

## User Stories

- 会话暂停时查看模拟器、构建后台进程和 Agent 分别占多少内存。
- 即使构建父进程已退出，也能找到留在此会话隔离组内的守护进程。
- 请求结束闲置进程；冻结或无响应的进程可强制结束，不必关闭整个会话。
- 手机上返回会话不丢失原终端；关闭进程页或切后台后停止请求。

## Technical Design

- `internal/memguard/processes.go`：递归读取专属 pane cgroup 的成员，从 `/proc` 读取父子关系、RSS、swap、启动时间。
- `internal/tmuxruntime/processes.go`：严格解析会话，拒绝共享 pane/scope，使用既有 tmux runtime 查询。
- `internal/session/processes.go`：公开 `roami session processes` / `process-stop`，API 复用同一 CLI/core 路径。
- `backend/api/session-processes.go`：已认证路由提供 GET 进程快照及 POST 结束动作，返回稳定错误码，禁止缓存。
- `SessionProcesses.tsx`：桌面 Drawer / 手机 MobileSubPage；仅打开时每 5 秒串行更新，后台停止，错误退避，卸载中止。
- 发信号前使用 pidfd 固定进程身份，再核对启动时间和当前 cgroup；无法验证则拒绝，绝不回退到不安全的普通 PID kill。
- Linux 使用专属 cgroup 与 pidfd；非 Linux 返回不可用，不影响构建与其余会话功能。
- 会话根进程受保护。SIGTERM 是正常结束请求；SIGKILL 可结束被冻结进程。不隐式结束子进程、不隐式恢复会话。
- RSS 含共享页，不能简单与 cgroup memory.current 等同；界面明确说明统计口径。

## Acceptance

验证结果见 [acceptance.md](acceptance.md)。
