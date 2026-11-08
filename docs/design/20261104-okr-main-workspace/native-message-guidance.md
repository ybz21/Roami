# 原生成员的群聊投递指引

## Product Design

成员向 Main 提问时必须进入待处理收件箱，进展仍留在群聊。当前原生启动提示把 progress 与 question 混为一段只含绑定和 text 的写法，成员遵循提示后会默认发 progress；正文中的 @leader 不能替代消息类型。真实 B站成员的两条请示因此没有进入 Main inbox，见 #810。

## User Stories

- 原成员在原任务、修订、run 下提出真实问题，Main 从既有收件箱处理。
- 成员读取同一线程的实际回复，重试沿用消息键，不换实例或向终端额外注入输入。
- 制作完成回调、发布许可与 Main 独立验收仍分别留证。

## Technical Design

`executors/roami_cli.py` 的原生启动提示显式讲清 kind、messageKey、commandKey、replyTo 和当前身份绑定。progress 不要求答复；question/blocker/handoff 使用现有持久 inbox；reply 引用原 post ID。提示不授予新权限，不新增运输协议、不改收件箱/目标唤醒逻辑，不把收件回执描述为即时回复或任务完成。完整初始化模板的 swarm-execution Skill 同步同一操作约定。

## Acceptance

复用既有 CodingExecutor 启动、Swarm inbox、去重、当前修订/旧 run/跨团队拒绝与协调唤醒回归；不为提示字符串新增同构断言。生产仍需原成员发实际带类型的消息、原 Main 回复以及原成员读取回复的证据，不能把文案或孤立单测当完整通信验收。当前正在执行的原成员不重启，后续轮次沿用原实例取得新提示。
