# 原团队自动审核与发布

## Product Design

用户把持续目标交给项目内原 Main；原 X、Bili、数据成员沿用既有实例和记忆。
Main 接收成员交付后独立读取、审核，通过后由原渠道成员发布；自动模式不固定逐条人工报批。
发布成功必须有真实平台 ID 和公开 URL，数据成员随后针对该对象采集、更新看板与复盘。
制作完成、文件冻结、审核通过和平台发布分别保留事实，不相互冒充。

## User Stories

- 同一内容事项改稿保持 businessKey，形成新冻结版本，旧审核不能用于新字节。
- 群聊交接与成员回执继续唤醒原 Main；不按轮次创建替代实例。
- Main 实际读取正文和图片后自动决定；执行器自述不能代替独立审核。
- 发布结果未知时先查原平台对象，不换业务键或新 run 重复发布。
- Connector 使用本轮真实发布对象，不能把旧视频观测算作新发布循环。

## Technical Design

### 权威数据与目录

运行时 agent DB 保存内容事项、冻结版本、独立审核及素材来源，现有 project-okr.db 保持指标、
Connector 确认、看板及复盘权威；两库不直接跨写。项目目录保存可读素材与回执导出，导出文件不是批准权威。

本段新增 Python schema 27，Go 备份兼容上限同步至 27；真实 26→27 迁移测试保留旧对话记录、
校验完整性与外键。候选、冻结版本、审核和来源记录不能原地更新。未部署前生产继续使用 26。

### 原成员素材冻结

`swarm_publication_prepare` 是 Main 的受管工具；原生 CLI 别名是运行时工具入口
`roami swarm publication prepare --input JSON`，不是宿主公共 CLI 的新增命令。

请求绑定 projectId/swarmId/delegationId/memberId/taskId/revision/runId，以及稳定 businessKey、
channel、已保留的 manifest 引用和 content 路径映射。账号可记录已核验数字 ID，但填写账号不授予发布能力。
宿主核对原目标、原成员当前工作、最新成功执行及独立验收后的任务状态。

manifest 包含 identity.taskId/revision/runId，files 每项包含相同身份及 path/bytes/sha256。
content.body/title/tags/subtitles 使用相对文件路径，images 为路径数组，video/audio 为单一路径。
Main 应先用 `swarm_verify` 独立验收本轮制作任务，再冻结；该验收仍不表示已发布。

Codex/Claude 等 CLI 执行结果不一定自带 artifactRefs。仅接受当前 run 的宿主交付索引与本次
成功执行报告明确引用的文件；不回落到同 owner 的任意文件。清单导入以保留的原清单为来源，
忽略清单自填的 root，使用宿主 workspace 准备回执和 sourceFile 定位文件。
按字节数、SHA 检查，复用逐级 O_NOFOLLOW 文件读取，拒绝路径穿越、文件/父目录符号链接、
跨轮次清单和变更素材。选中的文件存入 ArtifactStore，并保存不可变来源关系。

重试同一清单/路径复用原快照。之后磁盘改稿不改变已冻结字节；新内容必须新清单和新版本。
同一内容事项保持 businessKey，不能用版本 SHA、工具调用 ID 或 run 作为重复发布的逃逸键。

### 独立 Main 审核

`swarm_publication_review` 只允许原项目 Main，在当前分支、有效 lease、活跃目标和当前轮次执行。
协调批次额外限制原 delegation；不能借同一 Main 审核另一项目或另一目标的版本。
有更新版本后不能新批准被替代版本。重试保留原审核记录，改变同次决定或理由返回冲突。

正文要求成功的 artifact_read 全页覆盖冻结 SHA，且完整工具结果保留在 Main 的实际模型输入。
图片要求原 Main 的真实 file_read 快照与最新实际 prompt manifest.imageEvidence 匹配，验证原图
和快照字节；较早的图片输入不能替代最新输入。文件名、作者自检、元数据或只读了一页均不够。
异步文件检查后再次核对上下文；停止、撤销、遗忘、删除或 lease 变化不能落下有效批准。

宿主保存 exact version/manifest SHA、Main turn/assistant/lease、决定、理由和读取证明。
这是宿主不可变审核回执；不冒充外部密码学签名或平台发布回执。
本段未接通视频/音频内容审核，遇到这类批准明确返回能力不可用，不伪造“已经看完”。

### 发布执行与取数：后续接入

审核工具不会发送平台请求。发布器还需核验实际授权账号及渠道能力，并消费同一获准冻结版本。
由受管 task.steer operationId 绑定原渠道成员的实际应用轮次：校验 job 的 appliedRevision/runId
及 attempt.launch_id，不按文本出现“批准”授权新 run。

发起网络动作前持久记录业务事项、审核版本、原发布操作与尝试；未知结果必须对账，不能自动重发。
真实平台对象及公开 URL 回写后才交 Connector 取数。Connector 保持 Skill 组织方式，可由 Python/MCP
适配器执行；账号凭据不进入项目目录、Skill 或记忆。采集结果经现有确认批次进入看板。

当前没有可核验的 X/Bili 受管发布连接，不把模板开关、账号文本或旧视频数据当作通道已就绪。
完成标准仍是原团队至少两轮真实发布、取数、看板更新、复盘及下一轮续派。

### 每日唤醒

PR #789 已接入真实原目标日期槽，`daily-operations` Skill 调用现有通知入口，不新开 Main。
真实宣传项目为 Asia/Shanghai 09:00，项目独有 cron job 由项目独有 systemd timer 驱动。
一分钟 tick 不等于一分钟执行目标；job 自己按每日表达式判断到期。同日期槽重试复用通知与批次。
实际已验证一次受控定时触发与幂等，不声称未来日期已经执行。

## 验收记录

专项证据位于 `/tmp/okr-publication-ledger-20261108/`。其中源文件哈希、最终运行结果与后续
完整门禁应一并记录。隔离 fixture 证明协议和故障边界，不等同原项目真实发布。
