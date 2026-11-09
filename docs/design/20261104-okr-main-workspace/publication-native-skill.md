# 原生发布：最终提交与可信回执接线

机制原型沿用 [原 Skill 发布流程](publication-native-skill.html)，全部模拟状态仍不能作生产回执。[历史草案](publication-native-skill-before-submit-bridge-20261109.md)保留当时边界；当前用户已经明确授权原项目、原成员使用已成功的 Chrome／ADB 通道，不要求重建 OAuth/API 或逐条人工报批。关联 #761、#826。

## Product Design

用户继续与本 OKR 原 Main 对话。Main 独立审核具体版本，交原成员继续原任务；发布后的真实平台结果、取数、看板和复盘分别核对。当前已经存在实际发布，不能用“新接口未接好”把它们改称未发布；同时也不能把历史文件补写成当时不存在的宿主提交前记录。

下一层只包住原通道的最终提交与结果留存。制作、上传准备和最终提交分开：上传成功不是发布；最终动作之前保存原业务事项，结果未知只对账，不换键重发。对用户只显示待执行、处理中、待核对和真实结果，内部版本、lease与调用记录留在详情。

## User Stories

- 审核通过的版本由原成员执行，不创建同职责替身；使用原账号、原 Chrome 标签或原 ADB 设备。
- 日期未到时保留真实状态与原日程，不派相同预检。到期由原 Main 核对最新任务、冻结字节与既有回执，再续派原成员。
- 点击后中断或没有平台 ID 时保留未知；不能因命令失败自动再点。用户暂停后仍保存已发生的事实，不再授予新动作。
- 原 Main 核验公开来源，再交原数据成员更新确认数据；不能用工作者写的 JSON 或收件箱投递替代平台结果。

## Technical Design

### 当前已存在的模块与未接线部分

`publication/releases.py` 已保留不可变交接，并要求原持续目标、自动模式来源、审核资产及真实受管续派身份。`publisher_identity.py` 核对当前 task/revision/run 与实际 applied 的 steer。`PostJournal` 以项目/渠道/账号/业务键保留唯一事项与尝试；`NativeSubmission` 在原生动作前记录意图，动作后保留平台 ID。`NativeReconciliation` 关联冻结输入、提交记录及独立公开回读。X 与 B站公开核对代码已有独立模块。

当前 `NativeSubmission` / `NativeReconciliation` 没有运行时注册调用者，资源/账号 admission 和最终动作 adapter 仍未接入。这是明确缺口，不是这些内部类存在就已支持生产自动提交。已部署的 prepare/review/release、媒体 inspect/image 和原成员实际 Chrome／ADB 能力继续有效。

### 最小调用契约

新增仅给当前发布工作者的最终提交入口，输入仅为原 `releaseId` 与当前宿主观察引用。owner、project、Main、member、task/revision/run、账号、业务键、版本和通道从绑定身份与原交接读取，不能让调用者自报身份、任意命令、网址或“同意发布”。Foundation 别名随真实 schema 注册；在代码实现前不把下列动作名宣传为现有 CLI。

1. **资源准入。** 复用现有资源 lease、观察和人工接管机制。Chrome 使用原受管标签、最新观察和宿主账号探测；ADB 继续调用原 roami adb，但必须补可验证的设备/当前账号/场景观察桥，不能用工作者本地 JSON 代造 routeProof。账号探测需与同一资源、当前 run、lease/scene 和实际平台相符，不导出凭据。
2. **提交前准备。** adapter 只读核对最终预览、实际账号、标题/正文/ALT与已经选入或上传的媒体，以及宿主留存的上传来源摘要。不能只比较文件名。实际 UI 的规范化单列契约，不能放过实质内容替换。准备不创建新的观察身份来悄悄替换旧准入，也不点击提交。
3. **持久意图。** `NativeSubmission` 通过 `PostJournal.reserve` 保留唯一事项。提交前事务再次检查目标/暂停/当前原任务、同一审核与资源证明，然后记录提交意图及 prepared 摘要。这里的 post_submit 是动作前意图，不能在界面表述为平台已经收到。
4. **单次动作。** adapter 复用原 Roami Chrome 或 ADB 最终动作，不自建发布 API。只按同一观察/场景执行一次，不自动 retry；人工接管、场景变化或冻结源变化拒绝输入。动作前记录已存在时只允许状态查询/对账，不能再次点击。
5. **结果留存。** 平台 ID 必须来自这次动作的真实响应/观察，不接收任意 URL 自报。已知 ID 立即写 post_created；异常、停止和回复失败不能丢弃已发生的结果。没有 ID 保留 unknown，不拿一次搜索无结果证明没发过。
6. **独立确认。** 节点只读回查该已知对象，匹配实际账号、正文/媒体关联和冻结版本，再写 public fact。平台转码、正文末尾 LF 等允许规范化须显式验证。上传、提交、审核中和公开分别记录，不能互相替代。
7. **完成回调。** 可信 public fact 用于这一项具体发布的受管验收，不能放开任意 external_action 或成员自审。随后仍由原 Main 受管续派原数据成员，确认 Connector 批次和真实卡片，保存复盘/记忆并接下一轮或原日槽。

### 原 Codex／Claude 会话的入口

原生成员的 task_attempts.native_branch_id 可以为空；现有 `tools/cli_commands.py` 要求正在运行的 Python turn/toolCallId。因此只给 Python Worker 注册工具，不能宣称原 Codex/Claude TUI 已能执行，也不能为此换成一个新的 Roami Worker。

接入层应复用 Go `internal/agentexecution/session-lifecycle.go`、`internal/agentlifecycle/session-provider.go` 的原生会话/当前执行与停止证明，核验原 providerConversationId、当前 task/revision/run 及有效 launch identity，再通过内部受认证请求形成发布 binding。调用者的环境变量、显示名、任意 --task/--run 参数或本地 JSON 不能单独作为授权。当前原生工具与旧执行确实停止后，才允许推进同一成员下一轮；不重新实现一套进程清理或手改 busy。

这座原生调用桥尚未实现。隔离验收必须包含 native_branch_id 为空的真实原生成员路径，以及错 provider、旧 launch/run、暂停/停止和重复命令拒绝；不能只用 Python 模型 Worker 的模拟绑定证明原 Codex 接通。

### 模块与边界

运行时组装负责注册已有 journal/reconciliation 与新的原生 adapter；工具目录负责绑定当前工作者，不给 Main 任意设备 shell。平台 adapter 负责复用已有 CLI/driver 的账号与最终动作观察，不接管制作流程。公开回读继续独立且零发布写请求。项目 Skill 只教原成员如何调用真实注册入口、恢复原尝试；不把流程文字当权限凭证。

不修改模型路由、费用账目、环境或 busy，不关闭人工标签，不更换原 Main/成员/provider 会话。Root 不操作手机或人工账号页；实际资源验收由已获授权的原成员在真实发布窗口执行。缺少可验证的资源桥时明确保持最终入口不可用，原有已授权路径不被抹除。

## Acceptance

先隔离验证跨 owner/project/账号/资源/成员/旧 run 拒绝，冻结变化失效，实际 applied steer 与原 release 关联；证明 submitting 事务先于最终动作，并发/重启/重复回调不多发。提交后停止保留平台事实；未知不自动发送；伪造本地回执、缺页、错账号或错误媒体不能生成 public fact。

真实验收仍需至少两轮原 Main → 原成员 → 实际公开回执 → 原数据成员/Connector → 确认看板 → 复盘/记忆 → 后续原任务，不能由 Root 催促或模拟替代。此前15条X、10条B站的真实发布作为历史事实保留，不回补伪造的提交前事件。现有11-10 09:00窗口不提前，不为测试重发旧内容。

## 本次状态（2026-11-09）

本次只补接线设计，未新增工具、未操作设备、未接通最终 adapter，也未声称两轮闭环完成。已部署版本仍为 #842 / okr-runtime-7c492a91。#843 的复盘修复在独立源码跑完整门禁，不修改它的冻结源码。后续实现须按本契约补真实资源桥和隔离测试，再走正常 PR/合入/部署。
