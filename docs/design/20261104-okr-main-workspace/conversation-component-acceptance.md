# 共用对话组件验收（2026-11-07）

关联 #748。当前只交付前端共用组件；真实 `reply` 正文生成预览尚未实现，issue 保持开放。

- 仓库 full 通过；前端 typecheck、i18n、hover、生产 build 通过，全量 209 文件 / 1540 测试通过。
- 两个宿主使用真实 `useAgentThread` 与 ReadableStream/SSE，在 message.completed 前分别可见首段和后续正文。错分支增量被忽略，项目私聊只投递原项目 Main。
- 保留身份恢复、通知定位、旧 runtime 独占校验、附件、旧 pending、丢失回执原 key/payload、晚回不清新草稿、历史只读等专项。补充原 Main 改变时拒绝重投、SSE 已运行时仍使用原键恢复，以及队列 payload 在上下文更新后不重建。
- 自有 roami chrome QA 页运行旧/新组件，验证真实 HTTP SSE、增量正文、排队、项目目标、1280 / 1920 / 2560 / 3440 / 390 CSS px 无文档溢出，消息区与输入区均留在可用高度内。
- 紧凑模拟验证任务用一个全屏返回栏，返回原项目 Main；真实手机未操作，不计真机验收。项目宿主没有套入额外首页右栏。首页右栏开关与输入不重渲染已完成历史由既有专项覆盖。
- 按 staged diff，Go / Python / Python Skill 全套均跳过；保留已有作用域判定，不额外扩大检查。

本机证据：`/tmp/okr-shared-conversation-20261107/` 中 `final3-check.log`、`final3-check-exit`（0）、`browser-proof.json`、`browser-qa.log` 与 before / stream-first / after / compact / compact-tasks 图片。截图仅含隔离 fixture 数据。线上真实 Main 的只读事件证明该轮正文只有一次 delta，但不能把模拟 SSE 通过当作后端已修复。
