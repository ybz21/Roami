# 本机网关调用 Key

## 产品与用户场景

在“本机网关”标签配置其他本机客户端使用的调用 Key。用户可以输入、替换或确认停用；密钥输入在模型标签间切换时仅保存在内存中，不进入设置草稿的持久存储。保存后清空明文，只显示末尾八位。未配置时不新增调用凭据，已有智能体的自动密钥保持独立。

调用 Key 使用 16–512 个可打印的非空白英文字符。客户端可以使用 Bearer 或 X-Api-Key 调用目录及已有推理协议；调用沿用网关的预算、排队、转发和用量记录，不得到管理权限。

## 技术设计

- GatewayAccessKey 使用登录保护的 GET / PUT / DELETE `/agent/model-gateway/access-key`，读取配置状态、设置和停用 Key。写入校验共享目录 revision，冲突后保留输入并允许重新读取。
- Go 私有管理路由 `/v1/model-gateway/access-key` 由网关 Unix socket 承接，公网/loopback 推理 handler 不暴露它。
- catalogDisk 保存独立的 SHA-256 摘要、随机 generation ID 和末尾，不保存 Key 明文；目录快照与目录更新保留私有状态，常规目录 API 不暴露摘要。
- authenticate 将此凭据归为 external，拒绝与智能体凭据重合；keyAllowed 校验 generation，在替换或停用后唤醒并拒绝旧 Key 的排队请求。已获准的请求正常结束。
- 调用账目记录 external 与不可变 keyId，用量页面显示“其他客户端”；不更改 AgentKeys、Token 或智能体配置文件。

## 验证

Go 回归覆盖设置与重新加载、明文不落库、不泄露、推理转发时使用上游凭据、独立用量归属、普通目录更新保留 Key、替换/停用失效、管理路由隔离、排队撤销和已有智能体密钥保持。前端覆盖保存后清明文、冲突恢复保留输入、确认后停用。
