# RSI 对话契约、任务身份与过程错误

关联 [#446](https://github.com/ybz21/Roami/issues/446)、[#605](https://github.com/ybz21/Roami/issues/605)、[#635](https://github.com/ybz21/Roami/issues/635)。先读取三单的最新报告，保留所有历史成绩和未完成验收。

## Product Design

继续修复 RSI 已记录的问题。对话评测必须使用当前模型工具契约，保留每次工具失败；多个任务由同一条用户请求创建时，Main 必须能区分 taskId 对应的工作，同时保留完整用户要求。

Main 不新增工具。原题、输出要求、类型、验收阈值、节点模型配置、参数、权限、日程和历史用量保持原样。判定器只修正以既有输出要求区分任务身份的误报，不回写旧成绩。后台场景使用合成执行检查点，仅验证 Main 对话与任务身份，不声称后台产物质量通过。

## User Stories

1. 同一用户请求创建南、北两份报告；追问修改北区报告时，两个任务的上下文不能都只写“创建南北报告”。
2. 新版 Main 的 reply 只接收 text；RSI 替换目标目录服务后仍须保留这个模型可见契约。
3. 模型先尝试未准入命令、后改用已注册操作并完成请求；最终通过不能抹去第一次失败。

## Technical Design

### 已证明的框架缺陷

- `storage/task_context.py::recent_task_context` 原先只用原始用户消息标识每个任务。同一消息建立的多个任务因此显示完全相同的 goal。现仅对同源多任务补充已有 title，缺省时使用初始 goal 首行最多 80 字符；原 goal 字段继续保留完整用户原文。所有者、分支、时间、遗忘与来源校验继续生效，没有依据名称猜测或重写 taskId。
- `improvement/evaluation/conversation_scenarios.py::run_conversation` 在 Runtime 初始化后再次注册 Main 工具，覆盖了 `register_model_inputs` 已安装的模型视图。真实请求日志可见旧 reply 的六个字段与 delegate 的 requestComplete 必填项。现替换隔离目标服务后重新应用同一模型视图，旧内部 API 仍可用于协议夹具。
- 该隔离入口禁止普通 shell，但没有设置已有的 shell_disabled_roles，模型仍看到普通 shell 描述。现在使用同一个 Main 角色开关描述和拒绝未注册命令，并在执行前记录 executionStarted=false；原拒绝路径保留为防御。受限 shell 的目录描述改用 command，不再指导模型填写 argv。
- 同一路径只有模型用量，没有工具过程汇总。现从真实 SQLite 工具记录计算既有 tool_process_metrics，保存 execution-log.json，并在 CLI 汇总中按实际调用数、各 turn 首次调用数计算比率。未知或不完整证据的比率为 null，结构化语义错误继续由原判定器单独判定。
- `improvement/evaluation/conversation_oracle.py::grade_checkpoint` 原先会把“不要修改另一任务”中的名称计为身份候选；旧接口可选 title，简化接口只有 goal 时更容易遇到这种情况。现在仅在名称存在多个候选时，要求恰好一个候选满足原题已有的全部 contains 条件才消歧。原有全部要求仍继续检查，无法唯一判断、错误既有 taskId、合并任务或缺字段均不通过；没有添加任务专用名称规则。

### 验证边界

| 位置 | 对应环节 |
| --- | --- |
| [conversation_scenarios.py:272](../../../../../agent-runtime/src/roami_agent/improvement/evaluation/conversation_scenarios.py#L272) | 替换隔离目标服务后恢复模型契约，声明受限 shell |
| [task_context.py:38](../../../../../agent-runtime/src/roami_agent/storage/task_context.py#L38) | 同源多任务的短标题与既有来源保护 |
| [conversation_oracle.py:60](../../../../../agent-runtime/src/roami_agent/improvement/evaluation/conversation_oracle.py#L60) | 名称多匹配时依据已有全部输出条件消歧 |
| [conversation_scenarios.py:384](../../../../../agent-runtime/src/roami_agent/improvement/evaluation/conversation_scenarios.py#L384) | 读取实际工具回执并保存过程日志 |
| [run-conversation-scenarios.py:132](../../../../../scripts/dev/run-conversation-scenarios.py#L132) | 保留失败后的汇总与不完整证据空比率 |

新版评测仍拒绝任意宿主 shell，仅执行已有注册命令及场景任务操作。测试实际使用简短 delegate、字符串选项和 bash(command) 内的任务查询/续跑，不把“schema 看起来正确”当作执行通过。

完整用户来源不是任务完成证明；taskId 和执行器、工作区绑定仍由持久任务层校验。短标题只作身份提示，不把完整执行说明注入 Main。上下文修复提供区分任务所需的信息，不能保证模型永远选对任务，因此 #635 保持开放直到真实复测与问题验收足够。

## Acceptance Evidence

### 可复现反例与回归

在内存中加载 main 的原 task_context.py，保持磁盘源码不动：新同源多任务检查缺失 title，预期失败；原单任务检查通过。当前实现验证分别显示短标题、保留完整用户原文且不注入执行说明。

对同一份真实 Main 建立的三个合成后台任务快照，原判定器返回 TASK_IDENTITY_MISMATCH:周一名单，修复后的身份映射通过。此回放没有调用模型或修改原 trial；见[原快照回放](evidence/identity-oracle-replay.json)。负对照仍拒绝错误 ID、两个候选均匹配以及遗漏要求；JSON 的原文、键集合和严格类型规则未改动。

当前定向检查 **89 项通过**：16 个完整协议会话、schema 与实际简短 CLI 操作、停止/失败与用量未知、错误恢复后计量、加权汇总、身份消歧及负对照、Main 精简历史与可信交接回执。其后台仍为场景夹具，不作为真实产物交付。

首个“完整执行 goal 注入 Main”实现触发 4 项既有精简历史保护失败，已撤回并收窄为同源多任务短标题。该质量检查被主动停止，4 failed / 1626 passed / 28 skipped 只作为排查证据，不能当作质量门通过。

### 保存路由的实模诊断

已完成的逐次结果见[脱敏验收记录](evidence/conversation-verification.json)。每次创建新隔离数据库和私有 tmux 服务，复用节点保存的 Main 路由、模型参数、能力和 Go 统一准入；没有覆盖模型或补零历史未知用量。原始请求和日志留在本机。

| 运行 | 原始结果 | 结论 |
| --- | --- | --- |
| 旧评测入口基线，两组原题 | 1/2 场景，4/5 已观察轮通过，计划 8 轮 | 证明旧工具视图与 #605 仍可复现；未跑到的轮次不算通过 |
| 新工具契约的中间候选，三组聊天与一组续跑 | 1/4 场景，6/9 已观察轮通过，计划 17 轮；8 次工具调用，1 次错误 | 当时完整执行 goal 注入尚未撤回；不是最终交付源码成绩 |
| 普通叙述默认规则候选，四组聊天 | 4/4 场景，18/18 轮，2 次工具调用无错误 | 首轮通过，不能据此合入或关闭问题 |
| 同一提示候选的第二轮，完整 16 组 | 11/16 场景，44/49 已观察轮通过，计划 62 轮；84 次工具调用，23 次错误（27.38%） | 再次复现主题 null 与新增标题错误；候选未稳定，提示修改已撤掉 |
| 短标题与身份判定修复、shell 描述尚未对齐 | 两组任务通过，原聊天第 4 轮仍失败；共 16 次工具调用、3 次错误 | #605 保留；拒绝数据暴露出隔离边界描述不一致 |
| 最终工具边界、短标题和身份判定修复 | 原始三独立任务与澄清续跑两组均通过，6/6 轮；14 次工具调用、4 次错误，首次调用成功率 80% | 只覆盖两组原题，完整 Case 标记仍为 false；不宣称过程错误率已降低 |

最终 4 次失败调用来自 2 个模型批次：两个 `roami task_status ...` 非注册命令被拒为 TOOL_UNAVAILABLE；另一次 tool_list 与 ask_user 混合批次中的两个调用被拒为 QUESTION_MUST_BE_ONLY_TOOL。全部在执行前拒绝。两次批次问题不算四个独立根因；恢复后的最终通过仍保留全部四次调用错误。

各轮选题不同，不把表内场景比率直接相减或合并成统一成功率。对误判的原快照回放也不冒充新一轮模型生成。判定器源代码已纳入既有 grading_sources 指纹，不能沿用旧评分器身份晋级；历史 trial 未修改。

七轮实模诊断共 198 笔不同请求、942,654 tokens、0.2998368 元；逐笔匹配 Go 网关 198 份已知 HTTP 200 回执，无缺失请求。所有轮次保存的 Main 路由指纹一致，未改历史未知账目；费用只描述本轮诊断，不代表整体 RSI 成本。

### 工程质量门

最终源码的 `scripts/dev/quality/check.sh full` 通过：Python **3304 passed / 48 skipped**，Go、CLI 审计、格式、前端 i18n/hover/typecheck/build、秘密扫描和暂存文件检查通过。48 项环境跳过不当成通过。提交钩子的 quick 同样通过，Python 3304 passed / 48 skipped；完整回执见[检查记录](evidence/checks.txt)。

[源码哈希核对](evidence/accepted-runtime-source.json)确认交付的五份运行时代码/脚本与最后实模运行一致；Main 不增加常驻工具。原始完整日志保留在工作区，公开记录不包含模型提示、节点配置或凭据。

## 未完成项

#605 的模型语义问题、音视频与股票/PPT质量、独立评分证书、正式 60 项全套及两个实际观察日均不由局部设施检查替代；未启用自动日程或改写正式成绩。历史供应商中断与 401 的根因仍未证实，当前 198 笔已知回执不能证明历史问题已解决。

本轮没有重建冻结容器镜像或部署生产服务；新评分器与运行时必须以新的源码、镜像指纹进入后续正式验收。#605、#635 与汇总问题保持开放，提示候选和原始失败成绩均保留。
