# 本地网关与智能体独立计费：修订 2

2026-11-01，基线 `5d66fbe8`。[最新 HTML](gateway-billing.html)。按用户修订，直接使用节点现有默认智能体，不再增加自定义记账对象。

## 本次修改

- 去掉模型配置中的身份选择器、创建入口、账本中的额外筛选及同类命名示例。
- OpenCode、Claude Code、Codex、Pi、Roami 自动使用自己的 Key；Key 管理列表来自现有智能体注册表，不要求新建、命名或选择另一对象。
- 账本只按默认智能体筛选与汇总；Key 轮换不拆账，停用不删除历史。托管会话临时 Key 仍归到所属默认智能体，会话只作为明细。
- 技术方案移除 GatewayConsumer 和 consumer_id；Key、租约和调用记录直接使用 agent_kind。配置应用沿用现有 kind 参数，Key 操作按 agentKind 定位。
- V1 使用默认智能体 Key；V2 托管会话 Key 由系统自动签发，不增加手工选择步骤。

## 验证

- 内联脚本 `node --check`、`git diff --check` 通过；HTML 中没有已移除的选择器、创建入口、GatewayConsumer 或 consumer 字段。
- 桌面：模型配置只剩来源和模型；切换到 Codex 自动切换其 Key。应用、按默认智能体管理 Key、轮换、费用跳转均可用；轮换后的示例配置与展示 Key 一致。
- Key 列表固定展示 5 个默认智能体；没有创建入口。账本全部为 3 个有记录的智能体分组，已知费用 CNY 0.3600；OpenCode 4 次调用、CNY 0.2240、另有 1 条待核账；Codex 为 CNY 0.0856。
- Android Redmi Note 8：ADB 真实点按切换费用账本 / 智能体密钥；Key 列表正确，文档无横向溢出，导航 clientWidth 与 scrollWidth 均为 393 CSS px。账本仅有智能体和时间两个筛选。
- 仍为单文件 HTML，无外部库、产品 API 或真实凭据；未改线上功能。正式产品文案需接入现有中英 i18n。

截图：`/tmp/roami-gateway-billing-v2-connect-desktop.png`、`/tmp/roami-gateway-billing-v2-ledger-desktop.png`、`/tmp/roami-gateway-billing-v2-connect-phone.png`、`/tmp/roami-gateway-billing-v2-keys-phone.png`。临时截图不提交进主分支。

[初稿快照](records/2026-11-01/gateway-billing-v1.html) · [初稿验收](records/2026-11-01/gateway-billing-v1-review.md)。以上验证为设计原型，不代表真实鉴权、Key 写入、会话覆盖配置或计费往返已实现。
