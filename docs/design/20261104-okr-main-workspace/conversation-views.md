# 同一实例的对话与原生终端

## Product Design / User Stories

用户在 OKR 中点击与全局会话相同的 Codex / Claude / OpenCode / Pi 品牌按钮，切换渲染后的聊天和真实终端。保持一个入口、同一会话与草稿，不新增实例或回落首页 Main。切换按钮提供当前状态和下一步动作的可访问名称；粗指针使用至少 44px 命中区。

## Technical Design

AgentViewToggle 复用全局 TBtn，TerminalPane 与 SwarmMemberChat 使用相同按钮。成员目标仍须通过最新任务/修订/运行/执行器/项目/会话存活检查；身份变化移除旧视图。原生面板复用 Terminal，首次打开才连接，隐藏时保留真实尺寸；restore=0 禁止成员终端懒恢复为另一个会话。渲染模式保留受管发送路径和既有会话草稿键。

Pi 使用本机默认 ~/.pi/agent/sessions 的 JSONL 转录。受管会话按生命周期绑定的完整 provider ID 与文件头匹配，缺失/歧义不按目录兜底；普通会话用明确 resume ID 或当前进程开始后的唯一项目文件。按 parentId 投影当前已持久化分支，裁剪尾部窗口，忽略半行；变化窗口替换旧分支，空闲轮询只检查文件大小。文本、思考、工具调用/结果统一到既有聊天组件。暂不解析非默认自定义 Pi 存储目录，原生终端仍可使用。

## Acceptance

- frontend typecheck / i18n / hover / Vitest 全量 / production build；正常 full / commit hook quick 的实际日志保留在 /tmp/okr-conversation-views-20261106。
- Pi 源格式与工具配对、分支切换、半行与实例选择专项；成员四执行器目标校验及失效目标移除专项。
- 真实 roami chrome 操作隔离成员 UI，四类渲染适配器各连接相同的原隔离 shell PTY；输入标记经该原 session 的 CLI capture 独立核对，切回后草稿保留。该 fixture 不声称运行了四个真实模型 TUI。
- 1280/1920/2560/3440 CSS px，协作栏开/关共八档：无文档横向溢出，内容高度约970px，关闭后宽度归还对话。
- compact 390x844 + coarse 模拟：切换与草稿保留；未操作手机，未计真机触控通过。
