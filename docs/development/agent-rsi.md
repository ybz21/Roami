# Roami Agent RSI 评测运行手册

设计入口：[RSI 方案](../design/20261022-roami-agent-rsi/index.html)。已实现评测、有限参数候选搜索，以及发布/回滚和首页操作接口；新增能力仍待完整验收。现已接入独立ResearchWorker：语义复盘、持久工单、计量修复、源码A/B和评测实例观察；正式运行仍待验收和配置。正式测试机尚未绑定，不安装每日服务。

## 可运行范围

- `native_files`：真实 Roami Agent intake、上下文、工具、记忆提取和持久化。只开放受限文件读写、工具发现与回复；不开放 shell、委派、浏览器、桌面、现用会话或外部 CLI。适合财务 QA、结构化数据与文件任务；不能运行 SWE-bench、视频剪辑或完整桌面任务。
- `external`：约定好的本地程序或 SSH/容器包装程序，接入原生基准环境。仓库目前提供协议与超时清理，**尚未提供 Harbor、OSWorld、TheAgentCompany 等实际适配器**。隔离未被验证的外部结果阻止晋级。
- `protocol_fixture` / `smoke`：确定性模型驱动真实运行时文件工具，再由独立判定器回读。只检查评测设施，不计 Agent 能力得分，不参与候选搜索或发布。

正式混合套件缩减到 60 项：20 条公开任务、20 条自有真实任务、20 条机制回归。每天完整执行60项，稳定版/候选版各跑一次时为120个episode。新想法不替换正式题，只使用剩余实验预算。机制回归尽量不用模型；所有测试机共享日预算。80 条自建规格保留为候选库，其中40项已有夹具配方或运行时回归变体，仍需容器和判定器验收。不能因存在JSON就计作已通过案例。当前公开导入器支持 FinQA、ConvFinQA；其余任务须逐一接入环境、输入与判定器。GAIA 的访问条款仍由数据使用者处理。

## 安装与无模型冒烟

```bash
cd agent-runtime
uv sync --frozen
cd ..
scripts/dev/isolated-roami.sh /tmp/roami-rsi-smoke \
  agent-runtime/.venv/bin/roami-agent-evaluate smoke \
  --output-root /tmp/roami-rsi-smoke/results
scripts/dev/isolated-roami.sh /tmp/roami-rsi-smoke --stop
```

两条文件任务各跑 A/B，共四次执行。判定器检查真实 `output.json`；预期报告两组各通过两例，`verified_deliveries=0`、`eligible_for_promotion=false`。同一机器同一天重复启动返回已有周期，不重复消耗。换一个专用输出目录可重新验证设施；正式运行始终共用固定账本。

## 公开数据导入

先从上游固定提交取得本地数据文件，核对许可。不要把完整数据或答案提交到本仓库。导入器不自动登录或接受 gated 数据集条款。

```bash
cd agent-runtime
uv run --frozen roami-agent-evaluate import-finance \
  --source /private/datasets/finqa/dev.json \
  --revision 0f16e2867befa6840783e58be38c9efb9229d742 \
  --split dev --count 3 --seed 20261023 \
  --output /private/evaluations/finqa-suite.json

uv run --frozen roami-agent-evaluate import-finance --conversational \
  --source /private/datasets/convfinqa/data/dev.json \
  --revision cf3eed2d5984960bf06bb8145bcea5e80b0222a6 \
  --split dev --count 1 --seed 20261023 \
  --output /private/evaluations/convfinqa-suite.json
```

抽样按程序长度、表格规模分层，固定种子，保存所有不支持记录的排除理由。FinQA 当前只支持有数值 `exe_ans` 的记录，ConvFinQA 要求每轮都有数值答案。选择池大小和排除 ID 都进入锁文件，禁止运行后替换失败任务。需要“原样全部任务”的官方指标时，使用上游环境和评估程序。

Agent 只看到完整原始表格、正文和问题，不接收 gold rows、参考程序、答案或抽样锁中的判定数据。百分比按小数比例作答；ConvFinQA 不注入参考历史答案，每一轮都必须通过。这个改编分数是**组件的数值回答准确率**，不是上游程序执行准确率或官方榜单分数。

## 配置测试机和每日预算

复制 [machine.example.json](../../scripts/dev/agent-evaluation/machine.example.json)，提供独立 `evaluation-agent.toml`、冻结 suite、机器 ID、可信环境指纹与模型凭证的环境变量引用。所有相对路径相对配置文件；凭证不写进 JSON。`output_root` 目录必须私有，文件与账本权限为 0600。

`native_files` 的模型配置使用现有 `Settings.load()` 的 TOML 格式。评测请求固定关闭 HTTP 自动重试，输出上限最多 2048 Token。上线模型配置、Skill、MCP 和浏览器配置不会被复制进评测实例。原始 main/worker 指令保留，文件任务的受限工具配置记录为执行范围。

```bash
cd agent-runtime
uv run --frozen roami-agent-evaluate cycle --config /private/evaluations/machine.json
uv run --frozen roami-agent-evaluate watch --config /private/evaluations/machine.json
```

`cycle` 执行当天一次；`watch` 是独立长期 worker，在配置时区的 `hour` 后每天尝试一次，不占 Main 队列，不补跑停机期间的所有历史日期。适合由系统服务管理。多测试机使用同一中央账本、不同机器 ID；远程环境通过外部包装程序调用。SQLite 账本放在中央本地磁盘，不直接共享到网络文件系统。

每轮先原子预留 **A/B 两组全部选中 episode 的 Token 上限及次数**。超过日预算直接拒绝。当前采用保守预留，不回收未用余额；中断、用量未知也保留预留。每次模型请求用输入 UTF-8 字节量加协议余量、输出上限做保守准入，再按供应商用量结算。供应商未报用量、重试成本不全或超过预算时阻止后续请求。此限额不是供应商侧的金额硬上限，供应商侧配额仍应独立配置。

`auto_candidates=true` 只允许 development 套件。候选生成器按单参数缩减预算做有界搜索，用冻结的基线重新 A/B；下一天消费未试过的提案。失败先标为待诊断，不继续缩预算。它不是 GEPA/ACE 完整实现，不调用模型自改代码，不修改线上策略；需要更丰富的诊断策略时扩展 `policy.py`。

当前参数范围：记忆召回 1–16 条、召回 256–4096 Token、工具目录每页 1–20 条、近期上下文 1024–64000 Token。当前默认值分别为 8、2000、10、20000。角色指令、权限、评分器、隐藏集和工具写入权限不属于候选参数。

RSI主目标是主动测试→观察行为→提出修改→实际修改→回归验证。当前单参数搜索只属于辅助实验。行为观察器和隔离源码修改器已接入，其所有模型调用均计入同一日预算；未知调用不自动重放。用户日常使用记录不是必需数据源。

## 指标与评分

`native_files` 的计时从运行时启动至判定器验证结果可用；环境制作与数据库创建另属准备成本。`episode_ms` 额外包含即时记忆提取与关闭耗时。首段提交文本单独记录，不能代替交付时间。多轮任务共享一个预算；模型、worker、记忆提取、压缩等由同一个计量器统计。缓存与 reasoning 是供应商输入/输出的子项，不重复相加。

未来定时的 memory.daily 任务不会为单次评测等待至次日：记录 `deferred_maintenance_jobs`，保留 `observed_tokens`，完整 `tokens=null`、`token_coverage=partial_deferred_maintenance`，并阻止晋级。失败用 `elapsed_ms=null`、`right_censored=true`，不能以快速失败作为性能提升。工具耗时和上下文耗时可能重叠，不加总成总时长。

自动数值/JSON 判定只覆盖其冻结的客观合同。复杂任务保留待评分，不能把文件存在当 PPT/视频视觉质量。盲评需要两个不同评分人、校准版本，跨通过线或相差超过一档进入复核；未预登记优秀条件不能给四档。

比较要求案例、机器、模型与缓存模式可比，并保护全部基线通过项。发布诊断检查独立私有验证至少 24 例、隐藏配对至少 30 例，按独立 cluster 做 bootstrap，而不是把同模板变体当独立任务；隐藏与验证 cluster 不得重叠。隐藏质量差值 95% 区间下限需不低于 -1、交付率不低于 -0.02，至少一项达到预定改善，其他效率退化不超过 5%。样本不足、未知消耗、待评分、fixture、未验证外部隔离与不受控缓存都会阻止晋级。首版门禁较保守；发布与回滚按新会话绑定版本，尚未完成正式环境验收。

## 报告与恢复

```bash
cd agent-runtime
uv run --frozen roami-agent-evaluate report \
  --ledger /private/evaluations/private/ledger.sqlite3 --owner local
uv run --frozen roami-agent-evaluate recover \
  --ledger /private/evaluations/private/ledger.sqlite3 --owner local \
  --stale-seconds 7200
```

worker 每条 trial 更新心跳。超时周期恢复为 interrupted，保留已知 trial，不重放未知写入，不重新执行当天机器。`watch` 启动时恢复两小时前的过期心跳；正式试验单例最长一小时。

账本路径设为某节点 `data_root/agents/improvement/ledger.sqlite3` 时，该节点登录后的只读接口可查看结果：

- `GET /api/agent/improvement/cycles?limit=20`
- `GET /api/agent/improvement/cycles/{id}`

当前 Go 网关固定转发 owner=local；要从节点接口读取评测摘要，机器配置的 owner 需设为 local（示例已设置）。自定义 owner 的账本通过 CLI 读取。接口沿用 Go 登录认证和 owner 范围，只返回摘要，不暴露隐藏输入、参考答案、完整输出或轨迹。不新增 Main 常驻轮询。CLI 的完整 trial 详情只供持有本地私有账本权限的评测维护者使用。

运行记录在周期目录下：`manifest.json`、各 trial 的真实工作区和独立 `runtime.db`、`trial.json`、`report.json`。不自动清理证据，不将它们提交到仓库。


## 每日完整执行与运行日志回顾

每天完整运行冻结的60项，取消按4项抽样。稳定版与候选版各执行一次为120个episode；“60项”指独立case数。正式每日调度要求suite确实包含60项，现有40项自有包只能显式手动诊断，不冒充正式套件。

运行前必须足额预留整套A/B最坏Token与episode上限。预算不足时返回`RSI_FULL_SUITE_BUDGET`或`RSI_DAILY_BUDGET`，不缩减题目、不发起部分模型调用；缺正式用例返回`RSI_FORMAL_SUITE_INCOMPLETE`。示例预算Token设为0占位，需按实际冻结suite和多机分配配置，不自动增加预算。

每项保存`model-log.json`（实际请求、文本/工具响应与各角色用量）及`execution-log.json`（工具参数/结果、trace、错误与实际输出）。机制回归保存`regression.log`；外部runner须提供同格式`execution-log.json`，同时保留有大小上限的stdout/stderr。容器模型日志由宿主采集，容器内部trace保留为进程证据，不冒充宿主计量。

`behavior_review.py`逐项回顾成功和失败执行，扫描所有具体记录并生成带文件hash及record/span引用的发现：未知用量、重试、工具失败、未知写入结果、相同输入与结果的重复读取，以及配对质量/耗时/Token退步。建议是需要复现的假设，不能仅凭重复调用就删掉必要验证。规则回顾不调用模型，审查自身Token=0；后续语义观察/编码调用仍须计入日预算。

`review.json`是私有逐项回顾，`report.json`只保留覆盖、指标及回顾摘要。缺日志、缺项或回顾未完成，`daily_complete=false`并阻止晋级；中断保存`interrupted-review.json`且不自动重放。未知用量保留null，即使完成回顾也不能宣称效率已改善。隐藏/验证日志和答案不回流候选生成器。

自动参数提案用尽时仍执行完整套件并回顾，标为`baseline_stability`，不跳过当天。相同策略复测不能作为改进晋级。


## 自动研发运行

[图表版架构与执行](../design/20261022-roami-agent-rsi/automation-roles.html)。每日worker仍负责正式全60项；ResearchWorker自动消费已完成每日周期，逐次语义复盘、去重建内部工单、隔离补丁、独立源码验证、绑定专用评测实例，再观察两个后续完整日周期。所有阶段持久化，带租约和幂等键；付费调用结果未知时不重放。当前尚未启用正式运行。

| 执行环节 | 当前手段 |
| --- | --- |
| 复盘 | 继承主模型，每次执行独立上下文；按hash/record展开原日志，保护题的结果不反馈到优化侧 |
| 修改 | 原生模型生成受限补丁；硬Token上限、独立worktree、受保护目录检查 |
| 验收 | 冻结镜像、两组源码hash、基线只读测试；全60项与独立24验证/30隐藏门槛 |
| 应用 | 仅绑定专用RSI runner，后续两天全量加语义复盘后关单；退化回滚并重开 |
| Codex / 生产部署 | 当前未自动接入；缺硬Token计量适配或生产部署适配时不绕过 |

首次在本机配置。示例默认关闭，先填真实repo、已提交的base_commit、允许目录及私有验证suite；沿用已配置的Roami主模型。配置源代码执行范围只允许通过本地CLI，Web接口不接收任意命令：

```bash
cd agent-runtime
uv run roami-agent-evaluate research-config --ledger /path/to/data/agents/improvement/ledger.sqlite3 --owner local --config ../scripts/dev/agent-evaluation/research.example.json
uv run roami-agent-evaluate research-status --ledger /path/to/data/agents/improvement/ledger.sqlite3 --owner local
```

配置还需已有评测设置与注册suite：完整60项、container机器、明确日Token/episode额度、可用的roami-rsi-eval:local镜像。源码基线与镜像需兼容。A/B每台120次执行；多机不自动分片。额外源码验收还会跑60项A/B与私有验证，预算须覆盖这些成本，不能从每日全量中偷减。预算不足跨日等待；实际模型费用与预留量分开记录。

GET /api/agent/improvement/research可查看阶段与工单；POST /api/agent/improvement/research/{action_id}/resume恢复可恢复阻塞，未知费用需先对账。首页RSI页展示改进进度与执行记录。无新问题继续每日测试，测试者或修复者声称成功均不直接关单。

源码验证按受影响的Python运行时执行冻结基线回归；受保护的RSI评测器自身测试不作为候选修改面。失败日志保存在`checks/<action_id>/regression-*.json`，不把原始验证输出反馈给修复模型。

预算示例：当前每日A/B预留120次执行；同日推进一次候选全60项A/B及54项私有A/B，另需228次，合计至少348个episode额度。复盘和补丁模型调用另按输入字节与输出上限保守预留，展示实际计量；默认每次模型调用的准入上限64000，不能代替owner日额度。混合公开测试split的正式套件需关闭四参数auto_candidates搜索；语义复盘仅用development证据提出源码修改。

受控缓存条件通过本地`register-machine --ledger ... --owner local --config ...`登记，需明确`cache_mode`和`cache_attestation`；Web登记的默认机器保持uncontrolled，不凭容器隔离就宣称控制了模型缓存。
