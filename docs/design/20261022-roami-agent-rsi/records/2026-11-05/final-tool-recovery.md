# 未提交终答的原生工具恢复

## Product Design

Main可能已经准备好回答，却连续输出普通文字，最终停在MAIN_FINAL_TOOL_REQUIRED的重复修复。下一次请求明确选择原生reply工具；模型仍生成参数，宿主仍核验来源和内容。

## User Stories

- 未提交草稿恢复为真实工具调用后才交付，保留JSON类型及原文字段。
- 复核发现真实权限或信息缺失时，下一轮仍能提问。
- 提供方不支持选择或忽略选择时保留失败，不能执行替代的写入工具。

## Technical Design

Core只在拒绝未提交终答后为下一次Main模型调用设置请求局部选择，普通首轮、Worker、来源复核和依赖终结保持原路径。收到单个有效reply后清除选择；内容拒绝仍回到正常修复。所选调用混入其他工具时整批拒绝，不执行写入。已有重复修复停滞判定保持。

Chat Completions请求增加tool_choice指定reply；缓存键和执行清单记录选择。ContextVar由异步上下文恢复，不持久化节点配置。私有Unix桥接只接受Main的这一选择及包含reply的目录，在开始上游调用前拒绝其他选择。路由、模型、采样参数、能力、额度及结算仍沿节点配置和Go网关；这不是验证脚本临时改参数。

协议依据：[官方Chat Completions工具选择](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。兼容接口是否实际支持仍以保存节点的真实调用验证。容器能力final-reply-tool升为2，旧Actor在推理前拒绝；无模型渲染保持兼容。模型指纹及容器配置版本同步更新。

## Acceptance

- 最终main d5fca3ab的原题回放保留：9/10已观察场景通过，39/40已观察检查点，计划16场景62点；保留项目与执行器场景第3轮连续普通文字引发TOOL_ARGUMENT_REPAIR_STALLED。源码未改、清理退出0，152笔调用均Go known/200，583334 tokens、0.1986479 CNY。此版本未部署，生产仍为main-c6fce4d2。
- 相同HTTP控制在旧源码失败；加入请求选择后通过，宿主没有改写返回内容。
- 143项提交、来源复核与回执相关检查通过，覆盖真实HTTP、私有桥接、选择后的内容拒绝/提问、Worker、缓存隔离、不支持选择的HTTP400及旧镜像拒绝。第一次提问控制错误断言loop文本返回值，修正为验证message.completed的question交付；初始失败日志保留。
- 扩展的提供方策略、错误、容器准入及任务通路共377项检查通过。
- 其余完整门禁、保存模型原失败场景及全题复测随后记录，不以机制检查冒充真实语义通过。此前所有成功、失败、未知账目与正式60项成绩保留。
