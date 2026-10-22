# 任务、会话与工作习惯

2026-10-22 设计提案，尚未实施。入口：[可交互 HTML](index.html)。

同一 HTML 包含产品设计、用户故事、桌面／手机交互原型、技术架构、状态与接口提案、迁移和评审验收。

覆盖：工作习惯与既有 Roami worktree 能力结合、未确认结束会话的持续可达与筛选保留、首页任务栏显示可点击项目归属，任务详情统一进入专业／内部智能体会话。

原型只使用示例数据，不连接真实会话、模型或 Git。刷新保留本地示例筛选；“重置示例”恢复初始数据。

## 设计验证

[原型验证记录](verification.html)：最新直达会话与 native 托管修订：Chrome 51 项、Android 真机 9 项通过。截图为设计原型；尚未实施后端或运行真实模型任务。

## 首页位置修订

任务列表加载在首页右侧工作区，中间保留 Main；每条任务的项目名为独立链接，点击后进入所属项目。任务详情和会话也保留该入口。手机从首页任务图标进入全屏列表。首页与项目页分别记住筛选，返回不清空。

## 直达会话与 native 托管修订

任务行和详情的“进入会话”直接导航到原专业会话或统一 native 会话页。native 默认目录为 `~/.roami/agents/native/<UTC毫秒时间戳-随机后缀>/`，`.chat.jsonl` 保存消息与调用，`.session.json` 保存身份关联，`context/` 与 `blobs/` 保存检查点及大输出。拟通过 SQLite 事务 outbox 补写日志；关闭不删除，恢复不重跑副作用。当前仅设计和样例，真实托管尚未实施。

示例：[JSONL](examples/native-session-example.jsonl)、[会话元信息](examples/native-session-metadata.json)。

## 查看方式与当前状态

将本目录保留完整结构，用 Chrome 打开 `index.html`。原型的 CSS、JavaScript 和图标均已内嵌，不需要启动 Roami 或安装依赖；JSONL 和元信息示例位于相邻 `examples/`。设计稿中的拟议接口尚未实现，所有交互只更新隔离的浏览器示例数据。

当前运行中的 native 消息、分支与工具记录保存在 `~/.roami/database/agents/runtime.db`。本 PR 只交付设计和示例，不创建真实 native 托管目录、不迁移数据库、不改动产品运行行为。文档使用中文，属于开发设计文档的 i18n 例外。
