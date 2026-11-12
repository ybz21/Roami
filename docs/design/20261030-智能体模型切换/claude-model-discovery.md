# Claude Code 默认模型与目录发现

## Product Design

Claude Code 接入 Roami 模型网关时可选择“默认”，无需选择上游源或固定模型。默认在每次请求时解析到节点保存的 Roami 主模型。保留现有指定来源和模型的方式；已运行的 Claude Code 需重新启动才能加载新环境和目录。

## User Stories

- 选择“默认”并应用后，新启动的 Claude Code 使用 Roami 主模型；主模型改变后下一次默认请求跟随变化。
- 在 Claude Code 的 `/model` 中可选网关目录已配置的全部模型，跨来源切换而无需重复接入。
- 在 Claude Code 保存模型选择后，下一次启动保留该选择；选择 Default 回到接入时的默认模型。
- 未配置可解析的主模型时，保留来源选择与管理入口，不静默选用任意模型。

## Technical Design

`GatewayModelBinding` 在 Claude 来源选项中增加默认项，提交 `model=roami-default`，不带 sourceId。网关依据当前保存的主模型解析目录路由；旧直连主模型只在地址、凭据、协议和模型匹配已配置路由时可用。目录返回 `defaultModel` 供界面校验。

`GET /v1/models` 对 Claude 凭据将路由 ID 包装为 `roami-claude/<id>`，保留模型显示名；其他客户端仍使用原 ID。Claude 自动发现会过滤不含 claude 或 anthropic 的 ID，旧 existing-main/随机 ID 因此不会显示。请求解析包装 ID，账本保留真实目录 routeId，桥接响应保留请求模型 ID；原 ID 继续兼容。没有伪造模型能力或窗口。

默认别名保留为 roami-default，禁止新目录路由占用该 ID。引用检查解析默认和发现别名，保护使用中的真实路由。默认请求解析失败时返回 MODEL_NOT_CONFIGURED。

原生网关配置清理 ANTHROPIC_MODEL，改用 ANTHROPIC_DEFAULT_MODEL 与 settings.model，以使 `/model` 保存的选择可在下一次启动生效。Sonnet/Opus/Haiku/Fable 别名映射到接入模型，避免内置 Fable 绕过网关目录。新增字段同样备份、恢复；其他预设保留既有优先级。

目录限于网关已保存路由，不自动枚举所有上游接口。新注册模型在 Claude Code 下次启动时发现；组织级 availableModels 或更高优先级的 modelPicker 仍可能限制列表。

依据：[Claude 网关模型发现](https://code.claude.com/docs/en/llm-gateway-protocol#model-discovery)、[模型选择优先级](https://code.claude.com/docs/en/model-config#setting-your-model)。

## Acceptance Evidence

- Claude Code 2.1.322：隔离原生配置，真实打开 `/model`；菜单发现 Main model、Second model，分别来自两个来源。缓存中保存 `roami-claude/existing-main` 与 `roami-claude/fixture-second`。
- 在菜单选择 Second model 并按 Enter，Claude 确认保存为新会话默认。配置 `model=roami-claude/fixture-second`，没有 ANTHROPIC_MODEL 覆盖；重启 Claude 非交互请求返回 OK，模型用量键与上游观测分别为 roami-claude/fixture-second、fixture-second。
- `--model default` 请求返回 OK，用量模型为 roami-default，上游观测为 fixture。请求经过真实 Go 网关及协议适配；上游为隔离测试服务，未调用生产模型。
- Redmi Note 8：真实 ADB 点按“应用”和确认按钮，界面变为“Roami 模型网关 · 默认 / 已应用”；配置实际写入隔离 CLAUDE_CONFIG_DIR。compact/coarse，宽度与 scrollWidth 均为 392，文档 scrollTop 为 0。来源、应用和确认按钮均为 44 CSS px。返回栏与底栏保留。
- 桌面 1280、1920、2560、3440 CSS px：模型配置可见，文档无横向溢出、scrollTop 为 0；该变更位于既有模型配置弹窗，不增加工作区常驻栏。
- Go 回归覆盖默认随主模型变化、跨源路由、旧 ID 兼容、发现 ID/[1m] 解析、其他客户端目录隔离、缺失默认拒绝、引用保护、直连来源匹配与配置备份恢复。前端验证默认无来源应用、配置缺失、已应用状态、CLI 保存后的发现 ID 识别及已有来源选择。
- Vitest：234 files / 1,725 tests 通过。typecheck、i18n（5,473 keys）、hover 与生产构建通过。quick/full 质量门禁结果以 PR 记录为准；Python runtime/skills 未改，按范围跳过。
- 桌面/手机改前改后截图及日志留在 `/tmp/roami-claude-models-evidence/`，公开 PR 图片仅含隔离测试数据。
