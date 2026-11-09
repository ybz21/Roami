# 长期会话的增量整理

关联 #813。原始聊天、原 Main 与所有成员保持原样，不改变模型路由、参数或计费口径。

## Product Design

长期 Main 每轮协作后继续使用已验证摘要和新增回合。后续整理不重复向模型发送已经覆盖的原始旧全文。遗忘、来源变化或分支变化仍使旧摘要失效，必须安全回退，不以性能为由跳过校验。

## User Stories

- 第一次整理保留完整来源；第二次只合并有效旧摘要与新增完整回合。
- 显式指定新 focus 时重新处理完整来源，避免旧摘要已省略的新关注点丢失。
- 仍能按完整 sourceIds、哈希、branchEpoch 和 memoryEpoch 核对快照，原聊天不被改写。
- 用户修改、遗忘或切换分支时，不复用旧权限或敏感内容。

## Technical Design

`context/projection.py` 的 compact 准备阶段仍确定同一份完整原始 source，验证/激活阶段仍检查其完整 fingerprint 与 owner/branch/epoch。额外选择与当前分支、记忆版本匹配的 ready 快照，仅当 sourceIds 为本次完整 source 的精确前缀、原来源摘要与投影策略一致，且本次没有新 focus 时复用。

送往 `summary_input.summarize` 的历史数据改为“旧摘要（明确是历史参考，不是新指令）+新增源消息”；摘要器现有提示继续把整份输入作为引用数据，不添加真实用户消息。完整 source、sourceIds、source_sha256 和 policy_version 仍来自全部原始消息，不以摘要文本替换其身份。元数据可记录复用的 snapshotId，方便追溯。

无缓存、来源不匹配、分支/记忆版本变化、旧 cut 超过当前 source、投影策略变化或新 focus 时，使用原完整历史流程。整理期间实际来源再变化，现有激活 CAS 拒绝；不在生产中热补丁或重启当前整理任务。

## 初始诊断边界（历史）

2026-11-09 原 Main 已有覆盖 6682 条消息的 ready 摘要，当前历史 7734 条、原始内容约 2165 万字符。本次自动整理仍运行；模型请求有真实成功回执，未重启。只读核验显示旧摘要的 sourceIds、来源 SHA、branchEpoch 和投影策略匹配，但 memoryEpoch 不同。因此这一次不能复用该旧摘要，属于必须保留的安全回退；本修复不宣称能跳过它，也不将 ready 等同于有效缓存。

## Acceptance

隔离两次真实 compact：检查第二次模型输入不含旧全文、包含前摘要与新增配对消息，快照仍覆盖全部来源。覆盖新增 focus、来源变更、记忆/分支版本变化、旧摘要超出 source 及执行中变化拒绝。生产下一次有效缓存条件下独立验收，不能用提示变化或孤立字符串断言声称性能已改善。

实现初版的增量整理、原 context 与摘要输入专项共 27 项通过。两轮实际 Context.run 保留原聊天，第二轮只向模型传入原摘要和新增工具配对消息，保存的 sourceIds/SHA 仍覆盖全部原始来源；执行中修改旧来源仍拒绝激活。

## 生产验收

[PR #819](https://github.com/ybz21/Roami/pull/819) 已合入并部署；[issue #813](https://github.com/ybz21/Roami/issues/813) 在原 Main 的实际后续整理完成后关闭。当前 `okr-runtime-42b930e9` 中的 `context/projection.py` SHA256 为 `4e4bd9d9b7a7a7601ddd7c47e5753ecfaa686337472b005dedb99cbb3bbdc67b`，与验收实现一致。

原 Main 的整理任务 `1b3301f4db83407a81f317e6250b1a14` 已完成，宿主将新快照 `e4e9c991b76941e6b4be86feed059ca0` 关联到旧快照 `570a98d8822c4efbadf09f9a2e17376d`。只读解包原生归档核验：完整来源从 8739 条增加到 9524 条，旧 sourceIds 为精确前缀，两份完整来源 fingerprint 均匹配；branchEpoch、memoryEpoch 与策略版本一致，原始目标消息保留。

用线上同字节实现和实际留存来源重放选择阶段，输入为旧摘要加 785 条新增消息，编码后 3643078 字符；同一完整历史为 28330092 字符。该数值是只读重放结果，生产原始 HTTP 请求体未留存，不能称为直接抓包，也不据此宣称 CPU、内存或耗时改善。本次审计没有新增模型调用或改写生产记录。

验收文件：`/tmp/okr-incremental-context-20261109/original-main-cache-reuse-20261109.json`、`audit-production-cache.py` 与 `production-cache-audit.log`。当前记忆或分支条件发生变化后，下一次仍须重新验证有效性，历史复用成功不授予永久缓存资格。
