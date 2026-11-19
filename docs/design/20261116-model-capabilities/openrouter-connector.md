# OpenRouter 免费目录连接器

## 产品与使用场景

在模型源点「新建 → OpenRouter 免费模型」，填写 OpenRouter API Key 后拉取免费目录，勾选需要接入的模型。已保存的官方 OpenRouter Chat Completions 连接可以在「修改连接」里切换源类型。转换保留来源和模型 ID、密钥以及调度引用。既有接入模型仍在已接入列表，拉取后的可选列表只显示当次发现的免费变体。

通用 API、本地服务和插件账号在已接入列表与可选列表均可搜索模型。搜索匹配模型 ID、已保存名称或上游目录名称。已接入列表的搜索直接使用本地配置。

## 技术设计

模型源增加可选的 `connector` 字段。Go 网关固定 OpenRouter 连接的 HTTPS 地址、Chat Completions 协议和 Bearer 认证。入口复用既有模型目录读取，免费连接器仅接受 OpenRouter `:free` 变体或 `openrouter/free`，并要求输入和输出 Token 标价均为零。免费目录属于发现策略，网关额度和供应商请求限制仍分别生效。缓存指纹包含连接类型，目录刷新不会写入配置。

沿用模型源编辑器的目录、选中状态与保存流程。新增连接类型选项和独立创建入口。通用 API 保留完整目录和手动录入。

[OpenRouter 模型目录 API](https://openrouter.ai/docs/api/api-reference/models/list-all-models-and-their-properties) · [免费变体说明](https://openrouter.ai/collections/free-models)

## 验收记录

- Go 回归覆盖仅免费目录、完整通用目录、保留能力元数据、拒绝替代地址以及复用已保存凭据。
- 前端回归覆盖独立入口、按目录名称搜索并保存所选模型、已接入列表搜索不发起目录请求。
- 浏览器与真机截图随 PR 交付。
