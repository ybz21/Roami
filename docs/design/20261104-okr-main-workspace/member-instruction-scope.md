# Main 与成员的指令边界

关联 #720。用户给 Main 的整段要求通常同时包含配置、分工、发布和验收。Main 给数据成员的“只取候选、不发布、不写共享记忆”不是原文子串；旧 `task_steer` 因此把它替换成整段用户要求，导致成员接手 Main 的工作。

## 产品与用户故事

用户继续和本 OKR 的原 Main 沟通，由 Main 将限定工作交给原成员。群聊和成员页展示本成员的任务，Main 保留协调和独立验收。续派保留成员、任务、执行器和原对话，不创建替代角色；投递回执仍只代表接收。

## 技术实现

`TaskRevisions.request` 仅在实际任务绑定到当前 Main 的 swarm、且来源为该 Main 的真实用户消息时，保留 Main 编写的限定指令，标记 `instructionAuthor=main`。普通任务继续采用原来的用户原文限制；显式 `sourceQuote` 仍必须是用户原文片段，不接受伪造引用。请求覆盖声明使用独立 `authorizationQuote`，用于验证授权范围，不将该引用替换成员指令；普通任务保持原有引用执行行为。

原始用户消息通过现有 `sourceUserMessageId` / `task_user_request` 保留授权和遗忘校验。成员输入将原始请求明确标为 Main 的授权背景，限定其只执行本成员任务，不接手 Main 或其他成员的工作。Native 原分支显示限定任务，模型上下文同时保留带边界说明的原始请求；CLI 的原 session 接收限定指令和同样的授权背景。附件仍按原有完整性和遗忘机制校验，不从后台回执推断完成。

涉及模块：`dispatch/task_revisions.py`、`storage/task_request.py`、`executors/professional_brief.py`、Main 工具描述。

## 验收

独立测试通过已注册 native / Codex 成员续派，核对幂等冲突、伪造引用拒绝、群聊任务范围、真实用户来源、原成员/任务/分支保留，以及 CLI 实际提交到原 session 的输入。通过注册 Main 工具入口验证请求范围声明开/关；与既有续派、附件/遗忘测试合计 57 项通过（含带换行的原文引用恢复）。完整检查及 PR 证据保留在 `/tmp/okr-member-steer-scope-20261106/`。

此修复涉及 Python runtime；本轮按用户边界不热改、重启或强制升级线上 runtime。线上现有任务的历史回执保持原样，不能把隔离验证写成线上修复生效。
