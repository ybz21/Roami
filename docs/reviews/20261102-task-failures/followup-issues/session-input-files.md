# fix(agent): 已有会话追加消息丢弃用户附图与文件

## 复现与影响

历史截图消息 6f19dbd1…（2026-10-19）通过 delegate(kind=session) 成功提交，但该路径 main_catalog.py:310 -> TargetDirectory.send -> SessionDispatches.prepare 只把文字和回报通道写进 prompt，没有读取源消息 attachments。当前 654e16f7 仍可复现。截图/文件无声丢失，模型收到成功回执但目标看不到原图。

代码基线 654e16f7：`agent-runtime/src/roami_agent/conversation/session_dispatches.py:50-132; tools/main_catalog.py:121-128,310-315`。

## 修复与验收

在源消息和所有者授权边界内读取附件，校验未遗忘/未删除与 SHA256，再将 name/MIME/path/hash 的不可信数据引用写入持久 prompt。相同键重用原 prompt；未知投递不重发；不从其他历史消息抓图凑数。覆盖 session_send 与 delegate(session)、完整性失败、撤回和幂等。

## 去重与范围

已核对已有 issue：#418 为同任务/执行器关联，#398 为旧未知结果恢复，#595/#596 为运行时取消围栏与观测；本 issue 跟踪不同的交付边界或拒绝说明。历史任务只读取证，不向原会话补发旧图，不重放其业务。新修复追加到 PR #597，不合并或部署。
