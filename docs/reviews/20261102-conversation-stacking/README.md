# 多轮聊天与任务构建 RSI 回归

本轮通过 [PR #606](https://github.com/ybz21/Roami/pull/606) 新增四组独立扩展Case，共16段、62个用户轮次；既有40/60项冻结套件不变。测量只评估Main是否正确聊天、建立任务和追加要求，后台完成为合成检查点，不运行真实Codex/Claude、项目写入或实际交付。

| Case | 覆盖 | 对话/轮次 |
| --- | --- | --- |
| CHAT-STACK01（Case95） | 约束叠加、修改和删除、语言/格式、话题切换 | 4 / 18 |
| TASK-NEW01（Case96） | 同轮多项、连续新建、相似标题、先聊后建 | 4 / 14 |
| TASK-STACK01（Case97） | 连续追加、项目与执行器、图片版本、跨任务隔离 | 4 / 17 |
| TASK-SCOPE01（Case98） | 澄清、请求重放、跨项目、状态查询不误建 | 4 / 13 |

运行通过真实intake、Scheduler job、Main loop、Gateway和SQLite，逐轮读取任务数量、来源、持续ID、revision、字段、项目/执行器和附件。未来用户输入、expect及fixture脚本不进入模型请求。完整运行和部分诊断分开记录；失败、未测、未知用量与清理失败不计通过。模型使用节点保存的Main路由、参数和能力，通过现有Go网关准入；无Token、次数或花费上限覆盖。

## 最终验证

- 最终机制运行：**16/16段、62/62轮通过**，90次脚本化模型流、零真实模型调用，完整源码与合同冻结检查通过，隔离实例清理成功。脚本化10800 token为设施用量样本，不是实际费用。
- 保存Main的完整诊断：**15/16段通过**；12段任务创建/续作全部通过，聊天3/4段通过。预计62轮，实际观察61轮，其中60轮通过、1轮失败；失败段在第4轮停止，末轮未测，不补作通过。
- 真实测量120次调用，观察到971899输入+输出token，用量均已知；费用以Go账本为准。没有覆盖保存的模型、参数、图片能力或金额准入，也没有启动真实worker、项目写入、通知或会话发送。
- 保存Main回执的整仓 `source_unchanged=false` **保持原样**：并行的根目录pytest收集新增了3个视频Skill字节码缓存；逐文件审计证明原冻结文件0修改、0删除，运行时、判定器、输入、依赖及指令未变。新增缓存已单独归档清理，未改写原回执。该批作为诊断资料，不计正式晋级或独立验收；[脱敏回执与差异审计](verification.json)保留该限制。
- 定向回归106项通过，含四种真实进程禁用反例、来源/标题身份、反串任务、字段/JSON类型、宿主shell隔离、未知用量停批、历史套件与目录检查。
- 最终完整门禁通过：`env -u ROAM_HOME GOFLAGS=-p=1 bash scripts/dev/quality/check.sh full`，Go全仓、Python **3136 passed / 48 skipped（898.93s）**、ruff、i18n、hover、typecheck、生产构建44.24s及压缩、秘密扫描和文件策略均通过。
- 提交钩子完整重跑通过：Python **3136 passed / 48 skipped（953.01s）**，没有跳过钩子，重跑只加了遇错即停，不减少通过时的用例；Go包并发为1，未修改测试或超时。48个原有环境/opt-in跳过不作独立验收。
- 实现提交`eff68abb`；追加报告随同推送。

- 包括试题校准和所有保留复测，本轮共6批、320次真实模型调用，累计观察2433107输入+输出token，全部用量已知；不是只列最终一批以隐藏复测成本。各批明细见verification.json；金额仍以Go账本为准。

## 校准与保留记录

- 初次跨项目试题遗漏了“给定字段”的内容，模型正确追问；补齐空白模板字段后通过。这是题面修正，没有把合法澄清记成产品缺陷。
- 早期判定以整句新建指令匹配目标，且把“不修改另一任务”的边界提及当成串任务；已改用实际来源轮次、持续ID与短标题。数值/明确字段允许空白、冒号与引用符差异；JSON数值允许同值的1与1.0，布尔/字符串仍与数值区分。
- 禁止通知/部署检查原始用户约束的来源保留，不用同义改写判丢失；没有声称真实后台执行已接受这些约束。总数查询明确包括已完成任务，要求JSON整数，避免把活跃队列和创建总数混用。
- v1/v2/v3原始测量、判定失败与输入hash均留在私有运行目录，未覆盖历史合同或重写旧分数。最终合同为source-bound-oracle-v4，单独冻结并测量。
- 初次提交钩子在已有Go父生命周期测试遇到EINTR，单项复验通过；另一次现有Go CLI集成用例的5秒续作等待超时，单项复验通过。没有修改这些用例或无关Go代码。合同校准期间的全量检查、以及已失败的提交检查主动中止，未当成通过；最终完整结果以完成日志为准。

## 实际缺陷与未解决项

- [#604](https://github.com/ybz21/Roami/issues/604)：保留bash、禁用shell时，转发直接调用底层handler，绕过禁用检查。四种形式（host/workspace × argv/command）的真实临时文件反例在基线均失败；已增加转发前检查。新评测另外封闭未解析bash/旧CLI回退，仅允许注册操作。不是声称生产发生过越权。
- [#605](https://github.com/ybz21/Roami/issues/605)：三轮真实Main把新增字符串标题回答为布尔值；模型事件本身已含错误值。保留为模型语义质量问题，尚未证明通用代码根因，未用特殊标题补丁或宽松JSON判定掩盖，后续需要冻结A/B复测。
- 这组Case不评估真实绘图、文档视觉质量、生产任务最终交付或独立晋级条件；不部署、不改线上任务状态，也不重放旧未知写入。

## 复现

```bash
uv run --frozen --project agent-runtime python scripts/dev/run-conversation-scenarios.py \
  --mode fixture --output .roami/rsi-conversations/new-fixture
uv run --frozen --project agent-runtime python scripts/dev/run-conversation-scenarios.py \
  --mode saved-model --agent-config /path/to/node/agent.toml --data-root /path/to/node \
  --output .roami/rsi-conversations/new-saved-main
```

输出目录必须新建；每段有原始SQLite、逐轮快照、模型journal与receipt，汇总保留contracts.json及完整源码hash。原始记录不公开；公开报告只含合成场景、脱敏用量和检查数。代码与报告通过 [PR #606](https://github.com/ybz21/Roami/pull/606) 提交；没有部署。
