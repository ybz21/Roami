# DeepSeek Harness 与统一 Agent 注册表

## 产品设计

将官方 DeepSeek Harness（`dsh`）作为 `deepseek` 注册到既有 Agent 契约中。智能体目录、任务选择、文件交给 Agent、项目与终端派生菜单、会话筛选、竞赛与用量筛选使用后端返回的注册结果。新增 Agent 不再要求为这些入口逐个添加名单。

沿用现有卡片、按钮、选择器、全屏手机详情页与中英文本地化。尚未安装的 Agent 也展示。需要任务描述的执行器在空终端入口标记“单次任务”并禁用；任务入口仍可选择。DeepSeek 使用官方 Harness 鲸鱼图标，任务选择器和能力目录共用 `AgentLogo`；未知品牌使用通用 Agent 图标。

DeepSeek 采用官方 headless 模式，单次任务通过标准输入传入，标准输出作为任务结果、标准错误保留执行诊断。后台派发根据主机能力选择单次执行。当前未建立 DSH 原生会话与 Roami 的转录绑定，因此不声称支持常驻 TUI、原对话恢复或受管续聊。模型与凭据由 DSH 自身管理，不展示 Roami 尚未支持的模型配置按钮。

## 用户故事

- 用户安装 DeepSeek 后，能在能力目录发现它，在任务与文件操作中选择它。
- 用户从手机新建任务时，与桌面看到相同的注册列表；空终端菜单说明哪些 Agent 需要任务。
- 用户升级 Roami 加入另一种 harness 后，现有选择器、任务记录与用量筛选自动接纳新种类。
- 主智能体派发 DeepSeek 任务时，Go 确认执行器已经注册，Python 根据主机回执选择实际支持的执行模式。

## 技术设计

| 模块 | 职责 |
| --- | --- |
| `internal/agent/deepseek.go` | 注册 `deepseek`，定义 `dsh`、headless 参数、权限映射与 npm 安装来源 |
| `internal/agent/descriptor.go` | 输出显示名、启动命令、任务参数标记、安装与配置能力；安装来源由各 harness 自述 |
| `internal/agent/process.go` | 从可执行文件或 npm 包路径识别已注册 Agent；不扫描任务正文 |
| `backend/api/claude.go` | 在进程树中先识别主 harness，再检查其委派的子进程，避免子 Agent 改变会话标识 |
| `internal/agentinventory` | 从注册表生成安装、版本和升级信息；不另设安装包名单 |
| `backend/api/professional-agents.go` | `GET /agent/registry` 提供轻量元数据；原 `/agent/professional` 提供安装、额度与验证状态，并携带相同元数据 |
| `internal/cli/swarm` / `backend/okr` | 成员与角色校验直接查询 Agent 注册表；CLI help 自动列出可用种类 |
| `internal/agentexecution` | CLI catalog 暴露运行能力；拒绝对单次执行器创建持久会话；记录真实退出结果 |
| `agent-runtime/.../protocol/executor_kind.py` | 只验证协议种类格式；Go catalog 是注册与可用性的权威，不在 Python 重建白名单 |
| `agent-runtime/.../executors/roami_cli.py` | 使用主机 catalog 决定持久或单次执行，实际启动仍走统一 CLI |
| `frontend/src/agent-registry.ts` | 按机器共享元数据快照与请求；内容不变保持引用；页面卸载、切后台、节点切换沿用现有请求管理 |
| `frontend/src/agent-command.ts` | 兼容既有命令偏好，并支持 `agentCommands[kind]`；未知种类使用后端命令 |

目录使用 `displayName`；任务记录保留未来种类，不把它们滤掉。转录渲染能力单独保留在已实现的聊天视图上，不能因一个名称符合格式就请求不存在的转录接口。

启动命令表单等待偏好加载和当前 Agent 元数据再初始化，避免冷启动将 `deepseek` 类型名当成命令保存。后端默认命令为 `dsh --profile headless --permission-mode danger-full-access`，与现有任务自动权限的默认约定一致；用户自定义命令仍保留其显式设置。

### 官方契约与安装

本次实际下载并检查 `@deepseek-ai/dsh@0.2.2-rc.1` 的包内容、`--version` 与 `--profile headless --help`。该版本要求 Node.js 24.9 以上，支持任务标准输入 `-`、`--permission-mode` 与单次退出。安装和升级显式使用 npm 的 `latest` 发布标签，在执行时解析当前发行版本；应用不固定版本号。此处版本及 Node.js 要求只记录本次实测，后续以当前发布包为准。

```bash
npm install -g @deepseek-ai/dsh@latest
dsh web
```

凭据与 headless 模型配置由 DSH 管理。Roami 不复制用户凭据、不替换其模型路由。原生 DSH 支持按已有 Session ID 续跑，本次没有自动猜测或绑定这个 ID。

参考：[官方项目](https://github.com/deepseek-ai/deepseek-harness)、[CLI 契约](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md)。实际发布包的帮助输出优先于滚动更新的 master 文档。

## 验收记录

完整记录见 [acceptance.md](acceptance.md)。截图与机器回执保存在本机 `/tmp/roami-deepseek-evidence/`，不将一次性截图提交到主分支；如后续创建 PR，使用仓库 `pr-shot.sh` 上传到 `pr-shots`。

官方鲸鱼路径来自 [FishLogo.tsx](https://github.com/deepseek-ai/deepseek-harness/blob/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb/packages/client/ui-primitives/src/FishLogo.tsx)，保持原始几何与官方单色表现，通过 `--brand-deepseek` 适配深浅主题。MIT 许可保留在 `frontend/src/assets/agents/deepseek-LICENSE.txt`。
