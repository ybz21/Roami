# 首页与 OKR 消息隔离

## 产品设计

首页 Main 与每个 OKR Main 都有自己的持久会话。首页的消息列表、提醒、未读角标和已读操作只作用于首页实例；OKR 的消息从项目 Main 的消息入口读取。保留原实例及历史，不通过再建实例处理列表混显。

## 用户故事

- 在首页打开消息，只看到首页 Main 的回复和提醒。
- 在 OKR 查看项目 Main 消息，继续进入该项目原会话。
- 首页尚未加载或切换节点时，不短暂读取其他实例的通知。
- 首页全部已读不会清除项目 Main 的未读状态。

## 技术设计

现有运行时支持 notification-list、notifications/summary 和 reminders 的 conversationId 参数，以及 conversation read 接口。原手机消息页和桌面通知弹窗未传参数，读取了 owner 全部实例；全局角标亦如此。

AgentInbox 默认解析 useAgentInbox 提供的首页持久会话；显式传入的项目会话保持原范围。身份未取得时不查询消息；失败时提供现有重试。ConversationInbox 在 node/conversation 改变时重新挂载，将分页、提醒、异步导航和已读游标隔离；客户端再次核对消息 conversation_id。所有已读操作调用当前 conversation/read。

useAgentInbox 先取得首页身份，再读带 conversationId 的摘要，并验证响应回显身份。保留共享缓存、隐藏暂停与错误退避，不增加轮询。不修改消息存储、模型上下文、Main 绑定或群聊转发。

## 验收记录

- 真实线上只读身份：首页 kind=home_main，会话 f143…；宣传 OKR kind=project_main，会话 5c19…、项目 2026-1103-1155-3q0c，分支亦不同。
- 用户截图第一条消息 event 19457 的 conversation_id 为 OKR 原 Main；不是首页会话。
- 原有服务的按实例查询返回首页 unread=0、项目 unread=18，证明无需改运行时即可隔离。
- 专项：29 项通过，覆盖混合响应过滤、无身份不查询、已读范围、节点切换、提醒范围及原有引用导航。
- 前端全量：199 文件、1455 项通过。typecheck、5187 key i18n、hover、build 及正常 full 全部通过；纯前端差异按范围跳过 Go/Python。
- 隔离浏览器验收与截图：/tmp/okr-home-message-isolation-ui-20261106；不触用户手机，不把粗指针模拟计为真机触控验收。

关联 #702 / #658。本次完成首页通知混显回归；该 issue 仍有其他引用、导航及收信链路验收，不能据此整体关闭。
