# 所有 Agent 渲染视图铺满可用宽度

## Product Design

原始终端使用整个会话区域，渲染对话却将消息流限制为 768px、输入区限制为 816px，在宽屏中间留下大量空白。所有 Agent 改为占满当前可用区域，保留既有令牌内边距；打开侧栏后使用剩余空间，关闭后恢复宽度。

范围包括 Claude、Codex、OpenCode、Pi，以及复用相同组件的 Roami Agent。消息流、输入卡、排队消息、上下文整理状态一起对齐。不改变消息气泡的角色样式和内容内部的尺寸约束。

## User Stories

- 在任意 Agent 的终端与渲染视图间切换时，两种视图都利用可用宽度。
- 打开或关闭文件等侧栏时，对话随剩余空间伸缩，不保留空列。
- 手机上继续使用现有留白、触控目标和独立滚动区域。

## Technical Design

- `frontend/src/components/chat/conversation.css`：移除 `.conversation-transcript` 和 `.conversation-composer.tt-composer` 的固定最大宽度与居中外边距，删除输入区容器的重复限宽规则。宽度继续由 `width:100%`、`min-width:0`、输入卡 `box-sizing:border-box` 和父容器内边距决定。
- `frontend/src/components/agent/agent-chat.css`：删除上下文整理状态与排队消息的额外居中限宽，使用块级元素的默认可用宽度。
- 四种会话 Agent 均通过 `ChatShell`、`ConversationComposer` 复用样式；Roami 的 `AgentConversation` 及输入卡也复用同一套类名，不按执行器追加覆盖。
- 更新 UI 设计规范，替换原有 768/816px 的旧约定。本次无新增产品文案。

## 验收

组件浏览器夹具直接加载工作区的 `ExecutorSessionChat`、四种实际 Agent 容器和消息/输入组件，API 由固定合成消息替代；Roami Agent 部分使用相同消息组件、输入卡及布局类。夹具未连接生产会话，不测试真实模型调用或真实终端连接。改前对比通过恢复本次删除的原始 CSS 约束生成。

- 桌面：1280、1920、2560、3440 CSS px × 五种 Agent × 侧栏开关，共 40 种组合；实测消息流、输入卡及 Roami 附属状态条填满父容器内容宽度，无文档/主区域横向溢出，输入框和发送按钮命中正常，内容区保留可用高度。
- 中英文输入区检查；通过 CDP 坐标点按输入、触发真实输入组件的发送回调。
- Android：Redmi Note 8（`216d6a43`）Chrome，HTTPS/LAN 硬刷新，实际宽度约 392 CSS px，`compact/coarse`。五种 Agent 的消息流、输入卡均约 360.73px，填满扣除左右令牌留白后的宽度，页面无横向溢出；真实触摸滚动均移动约 259px，输入框/发送按钮命中正常，坐标点按输入并成功触发本地发送回调。
- `scripts/dev/quality/check.sh full`：通过，含 typecheck、i18n、hover、生产 build；Python/Go 根据差异范围跳过。构建有现有大体积 chunk 提示，无失败。
- `npx vitest run`：261 个文件、1914 项测试全部通过。
- Impeccable 对两份变动 CSS 的静态检测结果为空；图标扫描未发现本次新增符号。
- 截图：桌面和手机均保存改前/改后；窄屏原本已经受可用宽度限制，因此手机宽度保持一致。
- 本次只验证组件布局与本地输入回调；真实终端连接、真实消息投递和全局导航不在本次夹具验收范围。

本次临时浏览器脚本、原始量测 JSON、截图与检查日志保留在 `/tmp/agent-width-validation/`；截图通过 PR 的 `pr-shots` 孤儿分支保存，不进入主分支。
