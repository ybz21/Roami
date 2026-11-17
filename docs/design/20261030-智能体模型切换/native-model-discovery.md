# 原生智能体默认模型与目录切换

## Product Design

Claude Code、Pi、OpenCode、Codex 接入 Roami 模型网关时，都可以选择“默认”，无需指定上游源。每次默认请求跟随节点保存的 Roami 主模型；工具自身的模型菜单可切换到网关已配置的任意路由。来源与固定模型选择继续保留。

目录范围是已保存的网关路由，不自动注册所有上游模型。默认目标不存在时明确失败，不静默选择其他模型。

## User Stories

- 接入默认模型后，Roami 主模型改变，下一次默认请求跟随变化。
- 在工具原生模型菜单中跨来源切换，无需重新配置接入。
- 用户在原生工具保存的模型选择继续生效；网关配置不通过环境变量强制改回旧模型。
- Pi/OpenCode 的目录快照过期时，保留当前选择，提示并允许重新应用以同步清单。

## Technical Design

`GatewayModelBinding` 对四种工具提供默认项，提交 `model=roami-default`，不带 sourceId。`native-models.go` 根据节点主模型解析真实目录路由；旧直连主模型只在地址、凭据、协议和模型匹配已配置路由时可用。引用检查解析默认别名与发现 ID，保护使用中的真实路由。

| 工具 | 原生目录接入 | 刷新方式 |
| --- | --- | --- |
| Claude Code | `/v1/models` 中使用 `roami-claude/<id>`，通过其发现过滤；原 ID 继续兼容 | 重新启动 Claude |
| Pi | `models.json` 的网关提供商保存全部路由与默认项 | 目录变化后重新应用；`/model` 重读文件 |
| OpenCode | V1 `provider` / V2 `providers` 的 `models` 保存全部路由与默认项 | 目录变化后重新应用并使用原生重新加载或重启 |
| Codex | `model_catalog_url` 指向网关；带 `client_version` 且使用 Codex 凭据的请求返回 Codex Models 格式 | 重启 Codex 读取远程目录 |

Pi/OpenCode 预设保存模型目录快照；应用时由既有修订检查、备份及原子写入保护。轮换凭据保留完整清单。模型列表校验数量、重复 ID、选择是否存在及配置引用标记。Roami 页面比较保存快照与当前目录，过期时启用重新应用，不自动改写原生配置。

Claude 网关配置使用 `ANTHROPIC_DEFAULT_MODEL` 与 `settings.model`，清除会遮蔽菜单保存选择的 `ANTHROPIC_MODEL`。Sonnet/Opus/Haiku/Fable 映射到接入模型，路由解析兼容 `[1m]` 后缀；这只修复别名解析，不宣称上游具备 1M 上下文能力。

Codex 的 `model_catalog_json` 会遮蔽远程目录，应用网关时清除并备份，恢复时还原。目录元数据采用官方最小兼容设置，不宣称未验证的模型能力。模型元数据、窗口和工具能力仍由真实上游决定；没有修改 RSI 参数或配额。

外部 CLI 模型标签 `Roami Default` 是集成目录元数据；Roami 页面“默认”和提示通过中英文 i18n。

官方依据：[Claude 目录发现](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery)、[Pi 模型配置](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)、[OpenCode 提供商](https://opencode.ai/docs/providers)、[Codex 网关目录](https://learn.chatgpt.com/docs/enterprise/roll-out-a-gateway#model-catalog-reference)。

## Acceptance Evidence

所有调用使用隔离原生配置、真实 Go 网关和本地测试上游，不改生产配置、不调用生产模型。

- Claude Code 2.1.322 的 `/model` 显示两个来源的模型；保存 Second model 并重启后仍使用该模型；`--model default` 回到主模型，均成功返回 OK。
- Pi 1.5.2 的 `--list-models`、OpenCode 2.2.7 的 `models --standalone`、Codex 0.167.2 的 `debug models` 均实际读取到两个来源的模型及 roami-default。
- Pi/OpenCode/Codex 不指定模型的请求均使用主模型并返回 OK；通过各自原生命令选择第二来源的模型，也均返回 OK。测试上游记录分别为 fixture 与 fixture-second。
- Go 回归覆盖全部工具的默认跟随、跨源切换、原生目录、凭据轮换保留目录、缺失默认拒绝、旧 ID/[1m] 解析、其他客户端隔离、引用保护、直连来源匹配、配置恢复和 Codex 本地目录恢复。
- 前端回归覆盖四种工具无来源应用默认、保留现有来源选择、目录快照过期后保留选择并启用重新应用、CLI 保存模型后的识别。
- Vitest：234 files / 1,730 tests 通过；typecheck、i18n（5,474 keys）、hover 通过。quick/full、生产构建通过；Python runtime/skills 未改，按范围跳过。

此前 Claude 的桌面 1280/1920/2560/3440 CSS px 与 Redmi Note 8 真机点按已通过：文档无滚动或横向溢出，来源、应用、确认目标均为 44 CSS px；返回栏与底栏可达。扩展后的各工具截图和交互证据留在 `/tmp/roami-claude-models-evidence/`，仅将隔离截图上传 PR 图片分支。

扩展验收：Pi/OpenCode/Codex 的桌面与 Redmi Note 8 手机改前改后均已截图。三个桌面页面实际点击“网关 → 默认 → 应用 → 确认”后显示 Applied；手机三页均为 compact/coarse，视口宽度与文档 scrollWidth 同为 392，scrollTop 为 0。Pi 在真机以 ADB 实际点按网关、应用、确认，已应用状态与三个 touchend 事件同时确认；返回后回到智能体页，底栏保留。英文浅色与中文深色均实际打开验证。
