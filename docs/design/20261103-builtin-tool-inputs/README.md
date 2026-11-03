# 内置工具输入简化与过程错误计量

## Product Design

用户要求：本轮降低所有内置工具的输入复杂度，参考 pi / Codex CLI 的实际契约，不再要求模型填写可以由宿主绑定的执行元数据。RSI 必须考虑中间调用错误，不能只看最终完成。

Main 保持原有 11 个工具，不增加任务/会话直接工具，不提供浏览器和桌面工具；相关受管任务命令按需发现，浏览器/桌面工作交给 Worker。模型只提交动作本身和真正需要选择的目标。权限、工作区、并发版本、来源、幂等键、观测凭据仍由原有服务校验。外部 MCP 的服务契约保持原样；历史内部 API 继续接受旧结构。

## 已核对的上游源码

2026-11-03 核对本机 pi 1.4.0 及以下官方仓库实际 schema：

- [pi bash.ts](https://github.com/earendil-works/pi/blob/d71c66e05bdafd67e0558bfa65e748c71cd1f379/packages/coding-agent/src/core/tools/bash.ts)：command 是必填字符串，timeout 可选。
- [pi read.ts](https://github.com/earendil-works/pi/blob/d71c66e05bdafd67e0558bfa65e748c71cd1f379/packages/coding-agent/src/core/tools/read.ts)：path；offset/limit 为可选行范围，offset 从 1 开始。
- [pi write.ts](https://github.com/earendil-works/pi/blob/d71c66e05bdafd67e0558bfa65e748c71cd1f379/packages/coding-agent/src/core/tools/write.ts)：path/content。
- [pi edit.ts](https://github.com/earendil-works/pi/blob/d71c66e05bdafd67e0558bfa65e748c71cd1f379/packages/coding-agent/src/core/tools/edit.ts)：当前 schema 为 path/edits 数组，prepareEditArguments 仍接受 path/oldText/newText 的单次替换兼容格式。本轮使用这个已有的扁平格式，保留 Roami 单次精确替换语义；不宣称与上游批量编辑 schema 完全相同。
- [Codex shell_spec.rs](https://github.com/openai/codex/blob/bfdbf01bfaeaa6ab23b10e2bd64ed031fd1e5619/codex-rs/core/src/tools/handlers/shell_spec.rs)：exec_command 只必填 cmd 字符串，workdir 等由调用方按需覆盖。

上游工具本身仍使用函数参数对象；简化的重点是模型只写一个命令字符串，不再构造 argv 数组或选择内部 scope。Roami 使用 pi 的 command 命名及文件工具形状，不另造第三套。

## User Stories

1. Main 调用 `bash({"command":"roami help"})`，可直接获得帮助，不因 scope=host 被拒。
2. Worker 使用 `write(path,content)`、`read(path,offset,limit)`、`edit(path,oldText,newText)` 完成文件修改；宿主保护已读文件的并发变更。
3. 派活只需 goal，指定执行器时加 executor；默认走已保存的节点/项目设置。续跑只需 taskId/text，宿主绑定当前 revision。
4. 浏览器/桌面操作依据模型已看到的观测；模型不复制 observationId、图像凭据和 revision。
5. RSI 中先出错后恢复的任务仍保留错误计数和过程分；未知或缺失证据不当成零错误。

## 生产样本

用户截图对应轮次的只读记录显示，前四次调用分别被拒为 HOST_SCOPE_REGISTERED_COMMAND、USE_REGISTERED_CLI_CAPABILITY、ROUTING_PROFILE_CONFLICT、ROUTING_EXPLICIT_SOURCE_REQUIRED，第五次才接受任务。这四次均未开始执行，属于输入/准入阶段失败。

该截图与此前启动失败调查是不同链路。此前样本因旧 workspace writer 未释放，未启动 Claude；详见 [启动诊断报告](../20261103-workspace-launch-diagnostics/README.md)。本轮不将二者混称为 shell 运行失败。

## Technical Design

### 模型可见契约审计

| 工具 | 当前必填 | 可选输入 / 变化 |
| --- | --- | --- |
| bash | command | timeout；不再暴露 argv/cwd/scope |
| read | path | offset/limit，文本按行；skill://、artifact:// 继续支持 |
| write | path/content | expectedSha256 由宿主维护 |
| edit | path/oldText/newText | 精确替换一次；expectedSha256 由宿主维护 |
| tool_list | 无 | query/kind/offset；固定默认页大小，返回可执行 command 字符串 |
| delegate | goal | executor、directory、projectId、sessionId、fromMessageId；移除 routing、引文、requestComplete、requestCoverage |
| ask_user | prompt | options 为字符串数组；省略则自由文本 |
| reply | text | 不要求 mode/language/scopeQuote/coverage |
| task_reply | taskId | 移除语言覆盖与覆盖清单 |
| task_queue_reply | 无 | 当前队列状态 |
| task_steer | taskId/text | revision、sourceQuote、交接标记由宿主处理 |
| task_status | 无 | taskId/includeResult；按需发现 CLI，使用 command 字符串 |
| task_cancel | taskId | 按需发现 CLI |
| session_send | sessionId/text | 按需发现 CLI，沿用持久投递 |
| memory_search | query | scope/projectId/dayKey；默认范围由宿主提供 |
| reminder_create | text | kind/afterSeconds/whenMs/dailyAt；使用已保存时区 |
| browser_observe | 无 | 多个自有标签页才需 resourceId |
| browser_act | kind + 动作值 | selector/text/key/url/resourceId；不要求 observationId |
| computer_observe | 无 | resourceId/focusOnly |
| computer_act | kind + 动作值 | x/y/button/amount/key/text；不要求 observationId |
| conversation_history、workspace_overview、reminder_list、capability_overview、market_sources | 无 | 原本已最简，保留 |
| executor_catalog、session_dispatch_status、target_search、target_resolve、memory_get、reminder_cancel、host_processes、market_search、market_preview、market_install | 实际查询或目标参数 | 已为扁平输入，保留；市场安装仍要求具体预览和安装选项 |

内部 file_read/file_write/file_patch/shell/skill_read、旧 artifact 字节 API 作为兼容服务保留，不重复暴露给模型。未安装浏览器/桌面时不虚构对应能力。

默认配置下真实 Runtime 目录对比（JSON UTF-8 序列化字节，非 Token/CPU 测量）：

| 角色 | 工具数 前→后 | 顶层输入字段 前→后 | schema+描述字节 前→后 |
| --- | --- | --- | --- |
| Main | 11→11 | 39→23 | 15,328→4,859 |
| Worker | 5→5 | 19→13 | 3,885→2,101 |

Main 没有新增工具；明确校验其直接目录、能力发现、直接调用和 bash CLI 均不提供内置浏览器/桌面操作。原始目录见 [before](evidence/catalog-before.json)、[after](evidence/catalog-after.json)。

### 模块与状态绑定

- `tools/model_inputs.py` 定义简化视图；`protocol/tools.py` 保留旧参数校验兼容，旧字段出错仍返回对应旧字段诊断。
- `tools/foundations.py` 解析 command、默认绑定 shell 上下文、转换发现结果；受管 Roami 命令复用注册能力，不经普通 host shell 重复拒绝。
- `tools/main_catalog.py` / `dispatch/routing.py` 从简短输入生成原有 target/路由记录；继续做来源、所有权、可用性和目标校验。省略 executor 不增加一次模型调用或关键词路由。
- `storage/workspace_files.py` 从当前轮持久化读写回执恢复哈希，检查已读文件是否被改动；未读文件采用原子当前版本检查。显式旧哈希仍有效。文本分页使用 `storage/file_lines.py`，底层字节 API 不变。
- `tools/observation_inputs.py` 只选当前作用域中已交付给模型的浏览器结果，排除当前并行批次的新观测；桌面依据 prompt manifest 的图像证据。原有场景过期、所有权和停止围栏继续生效；多个资源要求明确目标。
- `tools/gateway.py` 为参数拒绝明确记录 executionStarted=false，修复建议同步简化契约。默认提示词和内置技能文档同步。

### RSI 为什么没有挡住，以及本轮计量

历史上确实发现过同类问题：[issue #359](https://github.com/ybz21/Roami/issues/359) 记录了 18 次请求中的委派参数反复修复。已有 `trace_metrics` 也记录 tool_failures。但结果评分、速度/Token 比较与该计数分离；最终断言通过可能掩盖前面的重试。Case 61/92 的固定机制回归验证代码路径，不等于真实模型第一次就会填对参数。

本轮 `improvement/integrations/tool_process.py` 从每次工具回执计算：

- tool_calls、tool_failures、tool_unknowns、tool_errors；已恢复的失败不删除。
- tool_argument_failures、tool_admission_failures（executionStarted=false）和错误码频次。参数拒绝是准入失败的子集，不重复相加。
- tool_failure_rate / tool_error_rate；shell 的非零 exitCode 即使回执 state=succeeded 仍计为错误。
- tool_process_score = 100 × 成功调用数 / 总调用数，与最终产物 quality 分开保留。
- tool_first_attempt_success_rate：Native 按 turn 第一条工具调用计数，覆盖 Main 和 Worker；没有 turn_id 的外部日志只按该次执行首条统计，不声称覆盖各个子 turn。

NativeExecutor 写入这些指标；隔离 Worker 和 RSI 工作流从实际 execution-log 重新计算，外部执行器也按日志计量，不能只采信 response 中的指标。trial summary 和周期回顾输出错误率及首次成功率。中断、截断、日志缺失或未完成调用标为 partial/missing，未知比率为 null；无工具调用的比率也是 null。

`domain/comparison.py` 在配对比较中阻止错误率、错误总数或首次成功率退步，即使最终结果通过且速度提升。新旧样本缺少可比过程证据时阻止晋级并要求重跑；缺少工具日志的真实执行不当成零错误。固定机制测试没有真实工具日志，不冒充真实调用成绩。过程日志仍是诊断证据，不升级为独立产物验收或可信用量证明。

## Acceptance Evidence

### 真实模型调用

使用节点保存的 Main/Worker 路由、参数和能力，经过现有 Go 模型网关；未覆盖模型、凭据、上下文窗口或生成参数。隔离数据库和工作区，不触碰用户会话。当前两条路由均解析为 deepseek-4.1-flash。Main 的 11 个工具在启用浏览器/桌面能力后也不增加。

实模验收：4/4 场景通过，调用次数见下方实际回执，工具失败/错误数均为 0，有工具的 4 个 turn 首次成功率 100%。模型分别只填写 command、空队列查询、prompt/options，以及文件 path/content/行范围/替换文本。验收脚本同时检查实际 stdout、提问选项和磁盘文件内容，失败后恢复不算通过。

- [真实回执汇总](evidence/live-acceptance.json)
- 脚本：`scripts/dev/agent-acceptance/tool_inputs.py`
- 运行：`scripts/dev/isolated-roami.sh /tmp/roami-builtin-inputs-acceptance-03 uv run --frozen --directory agent-runtime python ../scripts/dev/agent-acceptance/tool_inputs.py --output ABSOLUTE_OUTPUT`
- 隔离 tmux 实例已通过同一入口 --stop 清理。

### 机制与回归

`tests/test_model_tool_inputs.py` 覆盖真实文件写读改、持久化哈希恢复、并发修改拒绝、artifact 行范围、简短委派、自由文本/选项提问、CLI 帮助与受管任务命令与 Main 最小工具集、续跑幂等、浏览器协议夹具表单和隔离 Xvfb 桌面表单。浏览器 CLI 进程由 BrowserFixture 模拟；桌面使用实际隔离 Xvfb。两者的模型事件均由固定夹具生成，属于机制验证，不宣称真实模型视觉操作能力。

`tests/test_improvement_tool_process.py` 验证“失败→恢复→最终通过”的错误仍被计数、非零 shell 退出码、未知覆盖、不完整基线和过程退步晋级阻断。

最终定向契约回归 32 项通过，RSI 工作流 17 项通过，过程日志回归 5 项通过。full 质量门通过：Python 3,274 项通过、48 项跳过；Go、CLI 审计、格式、前端 i18n/hover/typecheck/build 和秘密扫描通过。quick 提交钩子通过：Python 3,275 项通过、48 项跳过，包含后补的损坏中断日志回归。详见 [质量检查记录](evidence/checks.txt)。首轮 3,318 项中的失败保留为契约迁移排查过程，不算最终通过证据。

## 未修复项与范围

- 4 个真实模型场景是小样本；未重跑整个 RSI 基准，不能推出全场景成功率或生产错误率已降低。
- 需更新部署版本后才影响运行中的服务；本轮未重启生产服务。
- 保留旧协议供持久化调用和 CLI 兼容；本轮不改外部 MCP/插件供应商 schema。
- 极长文本行按输出上限截断；read 的模型接口改为行分页，旧字节分页使用内部 file_read/artifact API。
- 历史 RSI 若无完整工具日志，不能补造过程错误率；应按新指标重跑配对样本。
