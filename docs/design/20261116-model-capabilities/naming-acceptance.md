# 模型名称与访问密钥

本轮沿用现有模型目录和配置字段，统一界面用词；不迁移调用 ID、不轮换密钥、不新增选模服务。

## 产品设计与用户故事

| 用词 | 保存字段 | 用户用途 |
| --- | --- | --- |
| 模型名称 | 模型 `name` | 在目录与 Agent 中识别模型，可重复 |
| 调用 ID（model） | 模型 `id` | CLI、API 和委派传参，唯一标识网关路线 |
| 上游模型 ID | 候选项 `model` | 识别服务商提供的模型，在详情或连接编辑中设置 |
| 网关访问密钥（API Key） | 已有网关密钥 | 客户端向本网关认证 |
| 密钥备注 | 密钥 `name` | 识别客户端或设备；修改备注不更换凭据 |
| 服务商 API Key | 模型源 `apiKey` | 网关向服务商认证 |

- 选择同名模型时，通过第二行调用 ID 与原生/聚合标签确认路线。
- 在目录复制调用 ID，直接用于 `roami model list` 所列模型及会话/委派的 `model` 参数。
- 为客户端创建访问密钥时填写备注，生成后明确执行“复制访问密钥”；列表仅显示带掩码的末尾。
- 修改模型名称保留调用 ID 与上游候选项。修改调用 ID 继续沿用已有旧 ID 别名兼容行为。

## 技术设计

前端沿用 `AgentModelPicker`、`GatewayModelDirectory`、`ModelHub` 与 `GatewayAccessKeys`；文案经中英文 i18n 输出。Agent 列表保留现有 ID 作为选项值，名称仅用于展示；内部 `gateway:` 选项前缀不展示为调用 ID。上游目录的 ID 明确标为上游模型 ID，只有已接入且可调用的网关模型提供复制调用 ID。凭据生成、重命名和一次性明文生命周期均使用原有 API。

未修改 Go、Python、数据库结构或已有用户配置。CLI 的 JSON 字段 `id` / `name` 与认证环境变量 `ROAMI_GATEWAY_KEY` 保持兼容。

## 验证

- TypeScript、i18n（5974 个条目）、hover 检查通过。
- Vitest：258 个文件、1887 项测试通过，包括同名路线选择、模型改名不改 ID、备注更新不替换凭据、分别复制调用 ID/访问密钥。
- 生产构建及 `quality/check.sh full` 通过；本轮仅改前端和文档，Go/Python 按影响范围跳过。
- 桌面 1280/1920/2560/3440 CSS px 下，选模弹层无越界、文档无滚动；实际 Redmi Note 8（392×766 CSS px、粗指针）通过触摸搜索调用 ID 并选择模型，选项命中高度至少 44px。
- 浏览器实际生成测试密钥、复制完整值、修改备注后认证仍返回 HTTP 200；关闭面板后明文不再显示。目录复制结果为网关调用 ID `free-text`，没有复制模型名称或上游 ID。
- 验收仅操作隔离实例。临时 JSON 证据保留在 `/tmp/roami-model-simplification/naming-browser-verification.json`，截图走 PR 孤儿分支。

## 合入与部署状态

前序功能 PR [#939](https://github.com/ybz21/Roami/pull/939) 已合入，主分支提交 `cdc44640d8dec1586b4ad56e2d34d80a409f52f8`。版本 `main-cdc44640` 的离线完整安装包已构建并通过候选检查。

本机升级保护返回 `AGENT_UPGRADE_BUSY`；一项已有委派执行的停止状态未知。官方 `reconcile-session` 返回 `SESSION_RECONCILIATION_SCOPE_REQUIRED`，未能确认停止。未强制中断会话、改写任务状态或绕过升级保护；当前运行版本保持原状。
