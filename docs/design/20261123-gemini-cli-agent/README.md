# Gemini CLI 接入 Roami

在能力中心的「智能体」中选择 **Gemini CLI**，可安装、检查版本、升级和打开终端。也可在新建任务时选择 Gemini CLI。终端使用 Gemini CLI 的原生界面，受管任务在任务对话中继续。Gemini 的账户、模型配置和用量由 Gemini CLI 管理。

用当前版本的官方包 `@google/gemini-cli`（本次以 0.70.0 验证）。在 Gemini 终端内完成登录。启动受管任务前，先在 Gemini 中信任实际任务目录或包含任务 worktree 的父目录。普通终端启动沿用 Gemini 的审批配置。受管任务的 `auto` 映射到 `auto_edit`，显式要求跳过权限确认的启动映射到 `yolo`。可在启动参数中指定模型。

- [Gemini CLI 官方仓库](https://github.com/google-gemini/gemini-cli)
- [Gemini CLI 登录](https://geminicli.com/docs/get-started/authentication/)
- [Gemini CLI 信任目录](https://geminicli.com/docs/cli/trusted-folders/)

## 执行契约

- [Agent 注册](../../../internal/agent/gemini.go)提供 npm 包、启动参数和完整 UUID 恢复命令。经 Roami 启动器创建的交互会话分配 UUID，传入 `--session-id`。直接从 Web 终端启动时，可用 Gemini 自带的 `/resume` 查看历史。
- [受管执行](../../../internal/agentexecution/structured-process.go)通过标准输入传任务，通过 `stream-json` 读取 Gemini 的结果。首轮从 `init` 获取 UUID，后续只用绑定的 UUID 调用 `--resume`。只有收到成功结束事件、工具调用已收尾、模型有最终答复且进程成功退出，才记录成功。
- [连接测试](../../../backend/api/agent-verification.go)在临时空目录中运行，账户和模型仍使用 Gemini CLI 的本机配置。

## 验收

- 在隔离实例中安装官方 npm 包，能力中心检查识别到 0.70.0，显示升级入口。
- 使用真实 Gemini CLI 的官方离线模型响应夹具，跑通单次任务和受管任务两轮。两轮返回同一 UUID，原生转录包含两次输入。回归测试覆盖失败、取消、会话 ID 不匹配和缺少终止事件。真实 Google 账户及线上模型响应未验证。
- 桌面 Chrome 在 1280、1920、2560、3440 CSS px 均显示 Gemini CLI 列表项，页面无横向溢出。在 Android Redmi Note 8 上点按列表打开详情并返回，再从详情启动终端。会话接口识别到运行中的 `gemini` 进程。
