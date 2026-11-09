# Main 的结构化 CLI 参数恢复

## Product Design

Main 完整读取成员产物后应能直接正式验收。注册 CLI 参数错误时，现有帮助给命令与 schema；对 JSON 还需说明其必须作为一个参数传入。恢复提示只说明编码方式，不回显原私有输入，也不自动执行猜测出来的修复。

## User Stories

- Main 在 command 使用 --input 时，将完整 JSON 整体引用；也可用 argv，把序列化 JSON 放在单一数组元素。
- 数组、对象和中文引号保持原始逻辑值，经相同注册 handler 与宿主绑定提交。
- 未识别/禁用命令与 shell 包装不获得新的执行途径；当前任务已改变仍由原校验拒绝。

## Technical Design

只更新 tools/gateway.py 已识别命令的 INVALID_CLI_ARGUMENTS 恢复文本。保留 foundations.py / command_families.py 解析器、角色目录与验证逻辑，不自动容忍错误语法。

在 test_command_discovery_inputs.py 经实际 Gateway 提交未整体引用的 JSON，确认 executionStarted=false、原 handler 未调用且结果无私有值；随后以正确引用的同一输入调用原 handler，确认复杂值和原绑定完整保留。现有 wrapper、禁用/角色及命令发现回归共同验证边界。

真实项目原 Main 的恢复、正式验收和分工纠正另行通过 Chrome 核对。测试通过不代替生产接线与实际任务状态。

## 重复验收的事实恢复

实际排队消息到达时，前一回合已成功验收同一 revision/run；再次验收返回 TASK_NOT_WAITING_VERIFICATION，被 Main 误解成原验收未成功。保留该错误码与拒绝写入，只在当前 Main/Swarm、任务修订及最新运行全部核对通过后，查询同一身份的真实 Main 验收事件。事件决定与当前终态一致时，返回最小 recordedVerification（事件ID、任务身份、accepted、状态），不返回私有 checks 或产物正文，不产生新决定、不覆盖旧决定。

终态但无真实 Main 事件、不同项目/旧修订/旧运行不得返回已验收证明；不同的新决定仍被拒绝。任务验收不授予新物料批准或平台发布事实。模板要求先核对当前事实，不能让过时排队快照触发重复审核或无意义续派。
