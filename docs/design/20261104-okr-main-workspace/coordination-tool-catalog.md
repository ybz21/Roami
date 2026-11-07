# 协调回合展示实际可调用的工具

关联 #744、#761。沿用[通信机制原型](communication-engine.html)和[同批次恢复设计](coordination-recovery.md)，不增加产品页面或按钮。

## 产品设计与用户故事

用户仍只与原项目 Main 沟通。Main 消费成员问题和交付时，应直接看到本次可用的入口，而不是按普通 Main 的完整工具目录试调用，再从拒绝中猜权限。普通人的 Main 对话和其他项目、成员回合继续依据各自能力工作。读取一个 Skill 只提供操作说明，不授予执行该 Skill 中任意动作的权限。

## 技术设计

沿用实际宿主 batch、delegation、turn、lease 和来源准入。`SwarmCoordinationPolicy.tool_names` 仅从真实账本识别协调回合；过期 lease、停止或遗忘来源在构建目录和实际工具执行时分别复核。模型不能靠 trigger 字符串或自己传 batch ID 取得权限。

`Tools.turn_catalog` 在每次模型调用前投影当前回合的工具，写入实际 prompt manifest 的 catalogHash。Foundation Main 保留 read、bash、tool_list、ask_user、reply；bash 明确只执行本批次注册操作，移除 edit/write/delegate 和全局历史等未准入入口。它不修改注册表、模型配置或其他回合的目录。

`ToolDirectory` 按同一操作集合生成命令、帮助、搜索结果、分页和 catalogVersion。`swarm_project_update` 只展示 record/review，`swarm_post` 只展示当前准入的 progress/question/reply；受管续派沿用原来的简短 taskId/text 模型输入，宿主从实际读取回执绑定 revision/run 和原用户来源，不把内部记账参数暴露给模型。通用 Roami help 在运行时重新投影，不能通过帮助绕回完整目录。协调目录不调用并附上全局 capability_overview。

目录用于准确发现，实际执行仍走既有 fresh scope、来源、停止和幂等校验；隐藏操作的注册别名也不能执行。本段不开放目标授权、群聊/日槽生产者或发布适配器；重试中的 record/review/记忆业务去重和同批次显式恢复继续按原设计实现后，再接入自动生产者。

## 验收

实际协调 fixture 覆盖模型连续两次请求与 manifest 哈希、命令搜索和帮助的参数范围、普通 Main/成员目录不变、停止/过期 lease/来源遗忘后拒绝读取，以及直接调用隐藏命令仍被拒绝。隔离模型回合用于验证宿主投影，不算真实平台自动发布、真实模型运行或手机触控通过。
