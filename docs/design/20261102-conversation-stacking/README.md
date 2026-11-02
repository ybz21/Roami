# 多轮聊天与任务构建回归

## Product Design

把用户连续追加、改口、分支话题、独立新任务和原任务续作做成完整对话；在每个用户轮次后独立检查真实持久化状态。任务数量正确还不够，要求、身份、项目、原执行器和附件也必须保留；无任务的聊天和状态查询不能产生任务。

## User Stories

- 我可以先聊清要求，明确开始时才创建任务。
- 一条消息中的独立工作可以分别建任务，相似标题也不能被合并。
- 给原任务反复补要求、换图或改条件时，不会新建替代任务或串到另一项目。
- 有多个相似任务时先澄清；重复提交同一请求不会创建两次，明确另建则产生独立任务。

## Technical Design

- Case95–98的`input/conversations.json`保存16段、62轮公开输入及宿主判定；fixtures仅供无模型设施回归。
- `conversation_scenarios.py`通过真实intake、Scheduler job、Main loop、Gateway与SQLite执行；项目/执行器目录和后台完成检查点为明确合成世界，不启动真实worker或会话。
- `conversation_actor.py`只负责协议脚本；真实模式通过已有`node_model_settings`和`configured_provider`使用节点保存的Main路由、参数、能力和Go金额准入，Actor看不到expect或fixture。
- `conversation_oracle.py`在每轮后核对任务数量、身份、revision、要求、附件和澄清；逐轮检查未来输入不提前出现，已有执行器、项目和workspace/session绑定不改变。
- `scripts/dev/run-conversation-scenarios.py`冻结源码与输入，创建/清理自己的隔离实例，保留完整和部分选择的区别、失败、未测及未知用量，不重复未知调用，不改历史正式40/60项或晋级门槛。
- 外部操作关闭，原始模型记录只留本机私有目录；公开报告只保留合成场景、检查数和脱敏回执。

## Acceptance

见[报告与执行记录](../../reviews/20261102-conversation-stacking/README.md)。范围是对话与任务构建，后台完成为模拟，不代表真实任务交付质量或“最佳对话”的主观评分。
