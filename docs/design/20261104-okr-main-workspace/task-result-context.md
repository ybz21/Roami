# Main 任务详情与对话历史

关联 #698 / #696 / #656 / #658。

## Product Design

查看一个任务的完整结果，只补充该任务结果；不隐式恢复整个 Main 的旧执行日志。
旧用户约束、必要回复和当前请求继续可见。明确查看早先对话时，沿用 conversation_history；
被遗忘的来源仍排除。页面和用户入口不变，不加入新的上下文配置。

## User Stories

- Main 读取原成员的当前结果，拿到完整证据后继续原任务，不因多年历史撑大输入。
- 用户明确追问旧决定时，Main 能显式恢复旧记录，保留来源与遗忘边界。
- 进度查询保持简短；完整结果不会被截成摘要或冒充成功。

## Technical Design

PromptBuilder 的 history_requested 仅检查当前 turn 成功的 conversation_history。
task_status(includeResult=true) 的真实结果继续作为当前 turn 工具消息进入 main_briefing，
不再关闭精简历史。任务工具说明和模型的结果范围提示也区分任务详情与对话历史。
普通状态查询的 task_progress 分支保持；不删历史、不改任务状态、
模型窗口或参数，也不施加新限额。

## Acceptance

真实群聊请求进入原 Main，10个工具后第11次模型请求HTTP400；读取约39KB的指定任务详情
同时展开了整段历史，估算输入775378。这个触发链可以证明范围放大，HTTP400本身不能单独证明
上游长度上限。

新增回归在修改前失败，修改后与历史/回执/文件图像/执行窗口相关78项专项通过：完整任务结果
保留，无关旧工具与回答保持折叠；显式恢复历史后原记录出现，被遗忘内容始终排除。

以线上实际源码、只读数据库、签名原生归档和项目文件复原失败请求，整体wire SHA与保存记录
完全相同。只替换候选PromptBuilder后，消息2278→75，估算token775378→42042；当前turn的10个
工具结果逐字节相同。这是只读对比，没有模型调用或线上代码激活。
证据：/tmp/okr-main-wakeup-release-20261106/result-context-real-fixture.json、context-targeted.log。
完整门禁与交付记录补在对应PR；原Main和成员保留，#696尚未认定恢复。
