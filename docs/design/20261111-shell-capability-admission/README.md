# Bash 命令执行与最终回复交付

## Product Design

截图中的 `roami task status --task-id … --include-result` 在 shell 启动前被白名单拒绝。Skill 文档可以提供普通 CLI 命令，工具目录未注册对应操作不应让 bash 丧失执行这些命令的能力。未注册命令进入现有 shell，返回 CLI 的真实输出及退出码；命令拼错时由 CLI 给出帮助。

## User Stories

- Main、worker、research 可以执行 Skill 提供的普通 Roami CLI 命令。
- 用户看到真实执行结果；旧版未执行回执继续保留原有含义。

## Technical Design

`tools/foundations.py` 保留已注册命令到原处理器的映射，保留项目/会话查询和帮助的现有快捷执行。其余 Roami 命令回落至现有 shell handler，沿用角色、工作区、禁用配置、环境过滤和输出归档。无新增执行器或权限模式。

`test_foundations.py` 用临时 CLI 可执行文件验证三种角色、command/argv 两种输入都实际运行，并保留参数、stdout 和非零退出码。`test_tool_rejection_evidence.py` 显式模拟旧版拒绝，验证历史恢复与重复错误检测仍有效。节点操作 Skill 的错误说明同步更新。

## Reply 交付

第二张截图的 `MAIN_FINAL_TOOL_REQUIRED` 并非 text 缺失。只读查询生产回执确认，模型普通最终文本被 loop 包装为 reply 工具记录，再被“必须显式调用 reply”规则拒绝；截图中的文本与对应回执一致。最近 300 条失败记录中，该错误 45 条，命令白名单拒绝 11 条。这是失败样本统计，不是所有调用的错误率。

普通最终文本现在由宿主送入 reply handler，使用与显式工具调用相同的内容校验、任务覆盖检查、来源审核与交付记录；不再为了调用形式要求额外一轮模型请求，也不再强制 provider tool_choice。请求级工具选择的桥接能力仍保留。系统指令同步允许普通最终文本，消除与 prompt_builder 的矛盾。

审计还修正了两个目录问题：未注册 Roami 命令保留 cwd/scope；Main 显式 cwd 不再被默认 host scope 覆盖。已注册命令仍由受管处理器校验，不将其权限错误转成 shell 重试；Shell 禁用、工作区范围、任务归属与未知写操作对账规则保留。

## Acceptance

- 基础工具与最终回复链路：105 项通过。
- 来源审核与容器指令：93 项通过。
- 文本流、交付、请求覆盖、恢复与历史回执：88 项通过。
- Ruff lint/format、git diff --check 通过。
- quick 质量门通过：Go 全量、Python 全量（`4789 passed, 48 skipped, 6 subtests passed in 1459.16s (0:24:19)`）、前端 typecheck/i18n/hover、CLI 审计和秘密扫描均通过。

本机日志：`/tmp/capability-reply-final-tests.log`、`/tmp/reply-review-check.log`、`/tmp/reply-contract-tests.log`、`/tmp/shell-capability-quality-final.log`。

未修改 Web UI，未部署或重启生产服务。
