# 群聊消息的 Main 失败反馈

持续跟踪 [#699](https://github.com/ybz21/Roami/issues/699)。运行态布局继续沿用本目录原型，不增加工作区面板。

## 产品设计与用户故事

用户在群聊交代工作后，如果 Main 没能处理完，需要在原消息旁知道失败，并直接回到本 OKR 的 Main。发送成功仅代表投递，不能用它表示执行完成；失败不自动重发，也不新建负责人。

每条失败消息下面只显示一句“Main 未能完成这条消息的处理。”和“查看 Main”按钮。完整错误、工具过程及重试决定留在原 Main 中。切过去再回群聊保留未发草稿，已阅读历史时不强制滚到底部。

## 技术设计

`storage/swarm_repository.py` 的既有快照在共享人类消息上附加可选 `mainTurn: {id, conversationId, state}`。它只来自该 post 已保存的 `turn_id` 和 `kind=message` 投递回执，并与本团队真实 Main 的 conversation 校验；定向任务转交、Main 自己的 post、其他对话或私聊的最新失败不参与关联。owner 权限检查沿用快照入口。

`swarm-protocol.ts` 扩展可选字段，旧运行时没有字段时不猜测失败。`ManagedSwarm.tsx` 复核 conversationId，只在群聊对应消息处显示 failed。按钮切换既有 Main 页签，继续原项目身份；不调用发送、重试、创建实例接口。状态跟随既有 Swarm 快照/SSE 更新，不新增请求、定时器或逐消息轮询。最新消息的执行状态变化参与自动跟随，用户已向上滚动时维持阅读位置。

布局只使用既有按钮和色彩/排版/间距令牌，中文英文均通过 i18n。动作可见，不依赖 Tooltip；不增加错误代码、内部 ID 或日志到主消息流。

## 验收记录

- 修复前真实群聊 post 已 accepted，但对应 Main turn failed 且没有最终回复；群聊缺少失败提示，证据保留在 `/tmp/okr-main-context-release-20261106/group-failure-feedback-proof.json`，不将私有对话截图上传公开仓库。
- 新回归在旧实现上分别复现快照缺少关联状态、页面缺少失败反馈；修复后 Python 协作/署名专项 48 项通过，前端全量 199 文件 / 1450 项通过，typecheck、i18n、hover、build 通过。
- 独立页面 fixture 只使用演示身份和内存 API，不访问真实任务或发送消息。四档桌面、协作栏开关、草稿保留和原 Main 跳转记录在 `/tmp/okr-group-failure-ui-20261106/{acceptance,pane-acceptance}.json`；独立触摸上下文的 390px 粗指针模拟在 `phone-acceptance.json`，44px 命中区四向检查通过。所有记录仍为隔离演示，不代表真机触控。
- 前置实现 `5fb60f96` 的正常 quick/full 均通过：Go全量、Python3702 passed/48 skipped、4组Skill与前端构建/静态审计；full为963.16秒。PR701已合入，当前不宣称Python运行时已激活，真实 Android 未操作、未计为通过。
