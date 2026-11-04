# RSI 未完成问题续修与完整核对

关联 [#446](https://github.com/ybz21/Roami/issues/446)、[#443](https://github.com/ybz21/Roami/issues/443)、[#445](https://github.com/ybz21/Roami/issues/445)、[#605](https://github.com/ybz21/Roami/issues/605)、[#635](https://github.com/ybz21/Roami/issues/635)，同时核对 [#350](https://github.com/ybz21/Roami/issues/350)、[#388](https://github.com/ybz21/Roami/issues/388)、[#398](https://github.com/ybz21/Roami/issues/398)。先拉取最新 main `01c6e435032a48b7abdcf4fae03579470d05c4b9`，读取各 issue 进展，保留历史失败、未知账目和其他活动工作区。

**全部 RSI 问题尚未解决。** 本轮修复三处可复现的工具层缺陷，并补齐原题复测、真实长调用与配置阻塞证据。内容质量、独立评分及正式全套不能由单元检查代替。

此前案例 65291b93 的启动链路、exitCode=-1 占位含义与历史频次已记录在[执行器启动诊断](../../../20261103-workspace-launch-diagnostics/README.md)和[任务目录隔离诊断](../../../20261103-professional-task-directories/README.md)：旧 writer 阻塞发生在 workspace_claim，CLI 尚未启动；本轮的命令准入拒绝、模型 401 与内容语义失败分别保留，不能归为同一根因。

## Product Design

模型应从内置帮助、MCP/外部能力发现和纠错建议得到同一种 `bash(command)` 输入；发生拒绝时，任务详情应能说明实际请求与出错阶段。Main 仍保持 11 个工具，不添加浏览器、桌面、音频或金融专用工具；内部参数数组和宿主绑定继续由程序管理。[实际协议控制回执](evidence/all-issues-tool-contract.json)显示 Main=11、无内置浏览器/桌面，帮助全部为字符串，默认 Main 的错误命令原文与拒绝阶段可读，外部模型请求为 0。

## User Stories

1. 发现一个已准入 MCP 或 CLI 后，直接填写其返回的命令字符串；无需把 `argv` 数组重新拼成 shell 文本。
2. 命令名、参数或工具批次被拒绝后，查看真实尝试输入与拒绝阶段，不再只看到 `{}` 或误导性的已启动事件。
3. 用户明确续作已停止的只读导航时，沿用原任务；写入未知、未停止执行及旧历史仍受保护。

## Technical Design

### 本轮实际修复

- [foundations.py:42](../../../../../agent-runtime/src/roami_agent/tools/foundations.py#L42) 新增只用于展示的命令转换：对副本把 `argv` 安全转换为 `command`，递归处理命令列表。`ToolDirectory.help_tool`（约 319 行）和 `register_foundations.list_tools`（约 464 行）统一处理帮助、发现项目及替代建议。旧实现只转换内置 CLI 的发现条目，`roami help` 和外部 MCP/CLI/HTTP 操作仍返回数组，与模型实际可见的 `bash(command)` 契约不一致。内部注册与设置目录保留原数组，不改准入或执行权限。
- [gateway.py:72](../../../../../agent-runtime/src/roami_agent/tools/gateway.py#L72) 原先校验异常后直接写 `args={}`，随后发出 `tool.started` 再次校验。现在保留第一次具体异常和有效 JSON 对象形式的尝试输入，入库后在执行前完成拒绝；回执包含 `failurePhase=validation/batch/command_admission`、`executionStarted=false`。JSON 损坏或顶层不是对象时，原始工具调用继续保存在关联的 assistant 消息，通过 `assistant_message_id` 可追溯，不把非法数据变成可执行参数。
- [loop.py:304](../../../../../agent-runtime/src/roami_agent/core/loop.py#L304) 的既有参数修复保护漏掉 `USE_REGISTERED_CLI_CAPABILITY`：默认 Main 会在 bash handler 的命令准入阶段拒绝未注册命令，但相同错误没有进入无进展检测。现在提供目录/帮助恢复建议，记录 `command_admission` 与未开始执行的证据，并纳入既有重复错误保护。只停止重复的无进展拒绝；修正命令后仍继续，不增加正常工具次数或任务预算上限。
- [gateway.py:475](../../../../../agent-runtime/src/roami_agent/tools/gateway.py#L475) 的 bash 纠错分支：保留可实际执行的简短命令示例，纠错要求从目录/帮助取得注册命令，不再建议把内部操作名直接当模型工具或 CLI 名使用。

拒绝参数仅保存在原会话权限范围内的执行证据，不回显到模型纠错提示。成功调用继续记录宿主解析后的规范参数；无数据库迁移，不重写旧记录，不重放任何历史操作。

### 原题与实模结果

使用节点保存的 Main 路由、参数、能力和 Go 统一准入；每轮冻结源码与输入，隔离数据库、执行目录和私有 tmux。下表均为新记录，没有拼接成正式全套成绩。

| 运行 | 场景 | 检查轮：通过/观察/计划 | 工具过程 | 结论 |
| --- | --- | --- | --- | --- |
| 最新 main 聊天基线 | 2/4 | 12/14/18 | 0 次工具错误 | 原题字段/类型问题仍可复现 |
| 保留较短历史回复候选 | 4/4 | 18/18/18 | 3 次调用，0 错误 | 首轮通过不算稳定修复 |
| 同一候选完整 16 组 | 13/16 | 52/55/62 | 89 次调用，8 错误，8.99% | 标题 null、首轮结构化值和任务续跑仍失败，未合入 |
| 精简协调提示候选 | 2/4 | 12/14/18 | 1 次调用，0 错误 | 未解决，未合入 |
| 合并重复 system 块候选 | 未取得可评分结果 | 0/1/18 | 模型返回上游 HTTP 401 | 停止自动重试，未合入；不能当作语义失败或通过 |

合并 system 块试验前两次为本地候选组装 `TypeError`，没有外部模型请求，均保留失败记录；修正实验入口后才观察到 401。本轮没有把任何未验收的提示/历史候选写进主交付源码。

完整 16 组中的 8 次工具错误来自不同原因：2 次内部名称被当作 CLI 命令、1 次受限角色尝试 shell 管道、同批 2 次不可用 read、1 次派活后的重复状态读取、同批 2 次结束工具混用。它们不是 8 个独立系统根因，也不能由最终恢复成功抹去。原请求仍可从 assistant 调用取回，正是这一对照暴露出规范工具记录丢失参数的问题。

[脱敏逐轮证据](evidence/all-issues-conversation-verification.json)：163 份不同 Go 回执，其中 162 份 HTTP 200，共 694,778 个已知 token，1 份上游 HTTP 401。已知费用合计 0.225614 CNY，本次 401 的 Go 结算为 failed、上游状态 401、费用 0，上游请求号为空；生成 token 用量仍未知。不能据此清零任何历史未知账目，也不能倒推历史 401 的原因。当前认证拒绝已定位到供应商响应阶段，尚无供应商侧日志证明凭据为何被拒。最终交付源码尚无新实模语义成绩，不能把先前候选结果当作新工具修复已改善错误率的证明。

### 执行限制与旧未知查询

- 执行限制、大输出、取消及进程相关检查：30 项通过；实际独立子进程 shell 连续运行 **65.012 秒**后退出 0，stdio MCP 调用 **120.110 秒**后返回成功。两次均没有显式 timeout，没有外部模型调用或路由覆盖；真实回执见 [长调用证据](evidence/all-issues-long-calls.json)。不把这两次协议检查说成实际模型超过 120 秒的验收。连接建立、健康检查与故障回收保护保留。
- 导航恢复、Native 工作区核对和路由回归：86 项通过。只读检查生产库中 #398 的原任务 `80ae85e32cce48cca43d647ed9fd1bc6`：revision=1、attempt=unknown；6 条浏览器动作仅有 new/goto，最后一条 `inputStopped=true/outcomeKnown=false`。当前 `dispatch/navigation_recovery.py::stopped_navigation` 返回 6 条动作及 1 条未知工具调用的停止证明，说明 PR #401 引入的后端只读恢复条件已适用于这条原始记录。
- 上述检查未修改原任务、旧 unknown 状态或浏览器。真实 Chrome 自然提问、沿用任务后的新查询交付仍受当前模型认证阻塞，#398 不据此关闭。未知写入、缺停止证明、仍运行的 turn/资源等负对照继续拒绝。

### 音频能力的隔离控制

实际准备并执行了[官方 VoiceFixer](https://github.com/haoheliu/voicefixer) 0.1.3 / PyTorch 2.5.1 CPU 工具链。首次自动下载中途断开，只收到 17,630,872 / 135,613,039 bytes；原部分文件保留，随后分段下载两份官方权重并核对 Zenodo 官方 MD5及本地 SHA256，校验完成后才加载。

仅挂载公开 noisy.wav 和已核验权重，未挂载隐藏 clean/window 参考；CPU 2 线程实际运行 46.063 秒，产生可读取的整段 PCM16 音频。输出为 44.1 kHz、1,322,956 样本，**不能直接满足原题 16 kHz、原长度与未损区逐样本保持的要求**。这是恢复组件执行控制，不是 Native 原题生成或质量通过；未新增/安装节点音频 Skill，也未用此结果替换旧 0.1235699 成绩。记录见[工具链回执](evidence/all-issues-audio-toolchain.json)，音频及权重留在私有实验目录，不提交仓库。

### 工程验证

原 `01c6e435` 两个模块在内存中加载，其他文件保持当前版本：新增 13 项缺陷检查全部失败；当前实现对应检查通过。另仅加载旧 core/loop、保留新网关时，重复未注册命令的保护检查失败，修正命令的控制通过（1 failed / 1 passed），定位到该漏分类而非模型或权限。测试包含外部 MCP/CLI/HTTP、Main/Worker、替代建议、帮助与内部目录不变，以及空格、中文、引号、`$()`、分号等文本按原值传递而不经过 shell 展开。

前版工具契约、纠错、文件输入和 MCP 路由专项 63 项通过；最终加入命令准入修复后，全部新反例、浏览器帮助角色准入及既有参数修复合计 25 项通过。现有浏览器帮助回归按新的 `command` 输出检查相同 click 命令，角色和禁止操作断言保留。

最终定向检查可从仓库根目录复现，使用独立测试实例：

```bash
scripts/dev/isolated-roami.sh /tmp/roami-rsi-tools-review uv run --frozen --directory agent-runtime pytest -q tests/test_tool_rejection_evidence.py tests/test_command_discovery_inputs.py tests/test_command_families.py tests/test_argument_repair_progress.py
scripts/dev/isolated-roami.sh /tmp/roami-rsi-tools-review --stop
```

最终 `scripts/dev/quality/check.sh full` 与提交钩子 `quick` 均通过：Python 各 **3318 passed / 48 skipped**，Go、CLI 审计、格式、前端 i18n/hover/typecheck、秘密扫描与暂存策略通过，full 的生产构建通过。48 项环境跳过不当作通过；本次没有界面改动。见[检查回执](evidence/all-issues-checks.txt)及[源码哈希核对](evidence/all-issues-runtime-source.json)，交付源码等于代码提交 ea2ffc08。前几次 full/提交钩子主动停止：扩大核对范围后发现外部发现/帮助仍返回数组、旧浏览器帮助测试仍读取 argv，以及默认 Main 的命令准入错误漏进无进展保护。中断及 teardown 错误保留，不当作通过；最终冻结源码后重新完整执行。

## 全部问题状态与未修复项

| 问题 | 本轮结论 / 下一条件 |
| --- | --- |
| #605 原文、字段及类型 | 仍失败；历史/提示候选全部未验收，原题、严格类型与 JSON 判定器未改 |
| #635 澄清后选错任务 | 完整对话集再次出现续跑要求未满足；新提示候选不可替代根治，需认证恢复后继续原题多任务及歧义负对照 |
| #350 执行硬限制 | 默认值核对、30 项检查与两次实际长调用通过；原自然对话及实际长模型响应尚未重新实测 |
| #388 唯一项目重复询问 | 当前已有精确目标搜索指引，但旧偶发失败不能据此关闭；保存模型认证恢复后按原题重复验证及同名负对照 |
| #398 旧未知查询恢复 | 原记录当前能生成只读停止证明，86 项边界回归通过；真实 Chrome 续作交付尚缺 |
| 音频 | 旧 Native v113=0.1235699<0.8 保留；隔离验证预训练恢复工具，不读取隐藏 clean/window 参考；工具准备不等于原题通过 |
| 原生视频 | v191/v193=0、v192 超时无原评分保留；工具抽帧/拼接成功不等于自主选片正确，新实模受 401 阻塞 |
| 股票/PPT | 旧 v190 严格 0/8 + 7 未评分保留；新报告的事实、统计、图表和因果解释仍需逐一验收，受 401 阻塞 |
| 独立评分与校准 | 实际预检返回 MODEL_IMAGES_UNSUPPORTED；Main/Worker 同为 deepseek-4.1-flash，Worker images=false，两条 endpoint/model 身份仅 1 个。需保存不同且均支持图片的评分路由，不能临时覆盖或放宽双模型要求；见[预检证据](evidence/all-issues-rater-preflight.json) |
| 正式 60 项与观察 | 新源码还需冻结镜像、完整执行与独立评分；历史 47 通过/4 待定/9 失败、0/2 实际观察日不改写；当前不能启动真实完整验收 |
| 历史流中断与 401 | 旧缺失的供应商请求号/日志无法补造；当前新增 401 已确认供应商返回，仍需恢复访问并取得供应商日志 |

#443/#445 与 #446 的重叠项目共用证据，不借重复 issue 关闭实际遗留。节点模型、能力、凭据、额度、调度、历史正式成绩、人工/授权 AI 标签均未修改；本轮未安装节点 Skill、未部署或合并新 PR。

[下载本报告](/api/file/raw?path=%2Fhome%2Fai%2Fcodes%2Fttmux%2F.worktrees%2Fagent-cc22707b574b864ad65abfc2%2Fdocs%2Fdesign%2F20261022-roami-agent-rsi%2Frecords%2F2026-11-04%2Fall-issues.md)
