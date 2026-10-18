# 记忆、文件与外部能力

## 动态发现

Main 常驻 read/bash/edit/write/tool_search/delegate/ask_user 共 7 个；普通原生 Worker 5 个，研究 Worker 3 个。新 Skill、MCP、HTTP 或 CLI 业务命令不能无限增加模型常驻 schema。

```bash
roami agent capability search --query "发消息" --kind cli
roami agent capability search --query "浏览器" --kind all
roami agent capability show session_send
```

模型使用 tool_search 得到相同目录信息，执行返回的 `roami agent capability call NAME --input JSON` argv。真实终端直接 call 还须 --turn / --call（或宿主注入的 ROAMI_AGENT_TURN_ID / ROAMI_AGENT_TOOL_CALL_ID），必须匹配运行中的父工具调用，不能从历史日志复制或让用户填写来制造新任务。CLI 可发现能力不代表当前角色可执行，执行时重新校验。

内置工具、Skill、CLI 固定启用且只读，设置页没有编辑 / 开关，API 返回 BUILTIN_CAPABILITY_READ_ONLY。外部 Skill、HTTP / MCP 命令才可启停。设置页有工具 / MCP / Skill / CLI 四 Tab；上传 / 导入尚为预留，不声称已安装。

## 自动记忆与检索

记忆按用户、任务、对话、每日与来源组织，自动提取与每轮召回。明确“记住这个偏好”的原用户内容可直接生效；推断内容保留候选，不能把助手自述当用户偏好。用户新要求优先。

- CLI `memory_search` 搜索历史记忆，参数以实时 schema 为准。不是 tool_search，也不是网页搜索。
- CLI `memory_get` 精确读已发现的记忆与来源；只用本用户可见的 ID。未发现不编造记忆 ID。
- 本轮没有通用 `roami memory save/list/delete` 命令，不能捏造命令。手动确认 / 遗忘在已有记忆页面或授权服务入口完成。
- 记录“已保存”须有持久化结果和来源；后续对话应该自动召回，不要求用户重复说记住。删除后不能从旧快照或输出面板重新展示已遗忘内容。

## 文件与产物

- read 普通文件受任务工作区 / 配置根目录约束；长文件按返回的分页续读，不把截断当完整内容。
- `read(path="skill://roami-dispatch/references/chrome.md")` 读 Skill 参考文档，不需要代码目录；未注册文件或路径穿越不允许。
- `read(path="artifact://实际ID")` 或 CLI artifact_read 读取用户可见产物。返回的 continuation / offset 以实际 schema 为准，原文件不假装已完整载入上下文。
- edit/write 先核对文件版本 expectedSha256，变更冲突重新读取，不覆盖用户改动。普通 Shell 使用已绑定 cwd，不能因缺目录就随便创建项目。
- 图片使用附件 / 模型视觉内容块；不要把 Base64 贴进用户消息或上下文报告。大图片走已有本地优化流程，token 估计与文件字节大小分开。

## MCP、HTTP 与 Computer Use

`tool_search(kind="cli",query="mcp")` 发现实际 MCP 能力目录；连接未配置或未发现远端工具时，返回空目录 / 实际错误，不声称已连接。远端 MCP 工具按注册 alias 调用，参数来自真实 schema，远端错误或结果未知不盲目重试。

HTTP 能力由节点配置注册，名称如 http_NAME；凭据由宿主注入，不写入 Skill、argv、报告或回显。浏览器页面读取不等于 HTTP 工具，配置端点不是可随意访问的任意 URL 代理。

Computer Use 由工作节点提供专属桌面资源，使用 tool_search 查实际 computer 操作。先观察、再基于 observationId 操作；动作失败 / 接管 / 未知按实际状态回报。未配置时不能声称有手机或桌面控制，也不能把 Chrome 的设备视口模拟称为真机操作。
