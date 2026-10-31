# 首版实现与验收

2026-10-31。交互已按后续反馈修订为“添加模型即全场景可选”，见 [当前设计](README.md) 与 [修订验收](revision-acceptance.md)。以下保留首版实现和验收记录，发布相关步骤由修订替代。真实产品实现位于 `feat/agent-model-switch`；设计 HTML 与模拟状态不作为实现验收。

## Product Design

能力中心并列“大模型”和“智能体”。大模型管理一个节点上的统一接入，添加多个模型源，再发布稳定的对外模型。智能体原来的安装、登录、启动和模型恢复保留在同一个目录，加入 Roami 主智能体与后台智能体。

大模型包含四个页签：

| 页签 | 首版行为 |
| --- | --- |
| 模型源 | 名称、上游地址、协议、认证方式和密钥；同一上游可建多条协议或账户配置 |
| 对外模型 | 稳定标识、真实模型映射、固定来源或有序主备；保存草稿与发布分开 |
| 用量与限额 | 原账本、币种、每日金额上限、时区、统计过滤和未知费用核对 |
| 模型定价 | 原默认价格及模型/前缀价格，分别设置输入、输出、缓存命中单价 |

价格沿用原来的账本和接口，迁移导航不会删除配置或历史。计价使用实际上游模型 ID，模型别名不会另计一次。高级模型能力、上下文和推理设置仍在 Roami 详情中。

## User Stories

- 配置者集中保存多条上游凭据，修改对外模型背后的来源后，使用它的工具无需逐个重填 Key。
- Codex、Claude Code、OpenCode 和 Pi 用户在原模型详情选择已发布且协议匹配的对外模型，确认影响范围后应用；新会话生效，并保留原配置恢复入口。
- Roami 用户分别选择主智能体与后台智能体模型，首次接入备份已配置的原连接与角色字段，之后可恢复。
- 财务配置者继续使用默认价、逐模型价、前缀匹配、缓存价和每日金额限额；旧定价与用量链接自动进入新页面。
- 手机用户通过分类选择器进入大模型或智能体；来源和模型详情以单返回栏的全屏二级页打开，保留底部四个目的地。

## Technical Design

### 模块

- `frontend/src/components/capabilities/ModelHub.tsx`：来源与发布编辑，以及复用原 `GatewaySettingsForm` / `GatewayReconciliation`。
- `model-hub-api.ts`：目录读写、版本冲突处理、空集合归一化，无新增轮询。
- `GatewayModelBinding.tsx` / `RoamiAgentModels.tsx`：外部工具和 Roami 角色接入。
- `route-hash.ts`：旧设置和定价链接迁移，保留节点参数。
- `internal/modelgateway/catalog.go`：目录、密钥、引用保护和版本校验，使用原 Go 账本数据库新增表；不改变原价格与调用记录。
- `catalog_http.go`：仅回环开放的推理入口，以及私有 Unix socket 上的管理和本机工具配置操作。
- `roami_binding.go`：通过已有 Python runtime 设置 API 保存/恢复角色，不直接改写 runtime 配置文件。
- `native_usage.go`：原生 Responses / Messages 用量解析；Chat Completions 复用原捕获器。
- `service.go` / `handler.go`：持久化回环端口，所有推理执行原额度准入与结算；Roami 内部转发直接进入同一个调用路径，避免双重扣账。

管理 API 经现有 Web 登录鉴权：`/api/agent/model-gateway/catalog`、`catalog/apply`、`catalog/roles`。推理入口只监听 `127.0.0.1`，没有管理 API。每种工具持有不同的网关调用凭据，上游 Key 不写入工具配置，也不回传浏览器。复用现有原生配置适配器的备份、版本校验与读回验证。

### 协议与安全换源

HTTP JSON 与 SSE 原样传递工具调用等负载，只替换模型名及上游认证。支持 Chat Completions、Responses、Messages，各来源明确声明一种协议；没有跨协议转换。

主备只在网络拨号失败、确定尚未连接上游时换源。HTTP 错误、超时、已输出或费用不明均不自动重放；未知用量仍以原有未知费用状态处理。缺少终态用量不会伪造为零费用。

首版不支持 WebSocket 及供应商 `previous_response_id` 续接，明确拒绝后者，界面提供兼容说明。公开别名缺少供应商模型元数据时，CLI 可能使用默认上下文等元数据；可通过原高级设置调整。需要使用方自行携带完整上下文。

原设计中的模型目录自动发现、连接诊断、能力自动验证、路由预览、加权路由、LAN 推理以及按别名/模型源汇总报表尚未实现。当前报表按实际模型和调用角色呈现。用户应为主备配置等价模型；首版校验协议，不自动认证工具能力或上下文等价性。

## 验收证据

测试实例使用 `scripts/dev/isolated-roami.sh /tmp/roami-model-hub-run`，独立数据目录、Unix socket、tmux server 和 CLI 配置目录。上游为本地 HTTP fixture，没有使用真实服务商密钥或产生外部消费。

### 自动化

- Go 全仓快速质量门禁通过；新增目录、密钥隔离、发布、版本冲突、引用保护、配置备份/恢复、协议转发、未知结算、主备不重放和 Roami 单次计价测试。
- `go test -race ./internal/modelgateway` 通过。
- 前端 typecheck、i18n、hover 审计、完整 Vitest 和生产构建通过。149 个文件、1119 项测试；定价回归还覆盖目录不可用时继续保存价格、旧 URL 迁移与草稿不发布。
- 未修改 Python 代码或依赖，按仓库规则跳过 Python 检查。

### 真实接口与桌面

通过管理 API 保存四种来源配置和四个对外模型，再从真实页面读取。旧默认价格、逐模型覆盖、每日限额和时区均保留。Codex 页面应用后读回当前默认模型为 `Roami Gateway / coding-main`，原配置备份仍可恢复。

真实 `codex-cli 0.166.0` 使用独立 `CODEX_HOME` 调用回环网关，收到本地测试源的 Responses SSE 文本后正常退出。原账本产生实际上游 `fixture-coder` 的已知费用记录；1000 输入、80 输出、100 缓存，按测试覆盖价格计为 CNY 0.0138。测试源初始缺少 Responses `total_tokens` 导致 CLI 重试，补全 fixture 后单次调用正常完成；未以这段无效 fixture 的重试作为产品通过证据。

Roami 角色绑定通过真实 runtime 设置 API 保存，并读回主/后台角色；Go 集成测试另外验证原连接恢复与每次调用只记账一次。

### Android

Redmi Note 8，1080×2340、DPR 2.75、392 CSS px，LAN HTTPS。通过 ADB 真实点按输入默认输入单价 11、保存，再从后端 GET 确认保存；实际滑动使内容 `scrollTop=112`，文档保持 0。模型源列表打开来源详情，返回到列表，再通过能力分类切到智能体目录。检查单返回栏、底栏、无横向溢出，补齐新选择器及下拉项的 44px 触控高度。

手机 Chrome 不提供 CLI 要求的 browser 实例 ID，使用 ADB 实际操作，直接 CDP 仅用于本任务页面定位、激活与布局读取；不修改 CLI 身份检查。

构建后再次检查分类选择器和全部八个下拉选项，稳定后的真实高度均为 44px。定价页硬刷新后保留默认输入价 11。录屏另外将逐模型输出价从 36 改为 32、每日限额从 100 改为 80，GET 读回均一致，默认价格与其他价格字段未被覆盖。恢复 Roami 后 GET 读回 `original-main` / `original-worker`。

产物通过 Roami 文件入口交付，不提交一次性媒体到主分支：

- [真实产品录屏，55 秒 MP4](/api/file/tmp/model-hub-implementation-demo.mp4)：来源编辑、主备草稿与发布、定价保存、用量与限额、Codex 应用、Roami 分别选模与恢复。
- [桌面定价截图](/api/file/tmp/model-hub-implementation-pricing.png)
- [Android 定价截图](/api/file/tmp/model-hub-implementation-phone.png)

视频为实际页面操作记录；录制器压缩无画面变化的等待时间。已解码检查，1280×800、545 帧，文件约 816 KiB。
