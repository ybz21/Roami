# 自动审核、发布与取数

## 选择工作模式

从用户目标确认本项目采用人工审批还是Main自动审核，以及渠道/实际账号和允许动作。自动模式不逐条向用户重复确认；模板、文件、任务成功和成员声明不能创建宿主权限。账号失效、通道缺失或范围不明要记录具体阻塞，不能冒充已启用，也不能把这种能力缺口改称永久人工审批要求。

## 一轮闭环

1. 原内容成员交当前轮文本、图像/视频/字幕、来源、轻量review.md和SHA清单，保留原件；不把含大量Base64的HTML图库作为唯一模型验收文本。
2. Main完整读取当前验收文件，检查事实、实际画面/字幕、链接和账号。冻结通过版本，关联项目、成员/task/revision/run、正文与媒体SHA；改稿后重审。制作交付通过不等于允许发布。
3. Main通过实际支持的受管入口续派原发布成员，按稳定业务键提交冻结版本。上传/HTTP成功不等于已公开；结果未知先对账原尝试与平台回执，不能换键重发。
4. 原数据成员读取Connector Skill，保留源响应、对象/账号、采样日期与单位，按候选批次和确认流程更新数据。Main检查确认看板；失败保留旧值，unknown不变0。
5. Main根据真实发布与数据复盘，CAS追加有来源的记忆，并以条目业务身份防重复，续派原成员下一轮。周期目录与原始历史保持原日期。

## 调度与验收

项目 Skill 按 `agents/main.json` 声明的项目文件路径读取；`skill://` 只用于当前全局目录实际注册的名称。先读 Skill 正文，再读阶段提示。包内相对路径以 `SKILL.md` 所在目录为基准，例如 `.roami/okr/skills/daily-operations/prompts/review.md`，不能拼成 `.roami/okr/prompts/review.md`。读取失败时核对声明路径，不另建日程或实例。

按[daily.md](daily.md)配置明确时间/时区和项目范围日程，只唤醒原Main。完成回调、普通群聊和日槽是不同输入，需要分别核验实际关联的Main turn、当前轮次、原实例和处理回执；不拿人的“继续”伪装自动调度。

至少两轮真实闭环后再称自动运行：当前版本审核、实际平台回执、Connector确认、看板变化和下一轮任务均有证据。设计HTML、禁用计划、投递成功或一次手动采集不替代它。平台凭证不写进项目文件、记忆或交付。

## Main 的实际工具入口

先读当前宿主返回的工具目录与 schema；内部日志名称不等于模型可直接调用的工具名。Foundation Main 用 `read` 读取 `artifact://<真实ID>`，而不是猜一个直接 `artifact_read` 调用。文本有 `nextOffset` 时按页完整读取；每页偏移沿用宿主回执，同一验收回合读取当前轮实际字节。图片应进入真实模型图像输入，不能只读文件名、元数据或 Base64 图库。

使用注册命令时，以单条命令和一个 `--input` JSON 传完整参数，不混用同名 scalar flags，不串接 shell 管道/重定向。下列是结构说明，不能拿占位符请求线上写接口：

- `roami swarm verify --input '<JSON>'`：`swarmId/taskId/revision/runId` 全部取当前真实回执；`accepted` 为布尔值、`checks` 为字符串、`artifactIds` 为实际完整读取的当前文本产物 ID 数组。文本验收不授予外部发布权限，也不能把二进制或外部动作伪装成文本验收。
- `roami project okr update --input '<JSON>'`：`operation="memory"` 时 `payload` 使用 `mode="append"`、仅新增的 `content` 和刚读取的 `expectedSha256`；冲突重读合并，保留旧字节。若目录提供专用 memory_append，优先用其实际 schema。CAS 防覆盖，不自动防止业务条目重复。
- `roami swarm post --input '<JSON>'`：Main 具名回告使用原 Swarm 与稳定 `messageKey`，普通状态用 `kind="progress"`。公共 CLI `swarm say` 是人的入口，不能用来冒充 Main 自我唤醒。

成员后续工作走原 task_steer，检查最新 revision/run 后再接续；不能用 legacy session_send 给受管成员另起一条独立工作流。旧直接消息 callback 只是独立回传，`verified=false` 保持不变；不凭该回传完成新任务。路由 guard、完成恢复与独立验收是不同宿主能力，按当前部署实测，不凭仓库文档假设已经上线。


## 素材冻结的输入与顺序

`content.body` 填清单内相对文件名（如 `01-post.en.txt`），图片填清单内相对路径数组；正文原文不是路径，不加项目日期目录前缀。`manifest.id` 使用宿主保留的 artifact ID，不是清单文件名或磁盘路径。以实际工具 schema 为准。

先把原成员整批素材冻结并逐条独立审核，再续派该成员到发布轮次。prepare 失败没有产生冻结版本；保持原 businessKey 修正输入，按实际错误处理，不把参数错误改称账号未核验，也不以手工“已冻结”声明代替宿主回执。原成员已推进时保留旧历史，使用当前受支持的恢复流程。

## 验收之后的下一步

持续目标的成员交付经 Main 验收后，在同一回合读取原任务的最新状态，选择一个有界的下一步，使用原 `task_steer` 接续。已有原成员正在执行或确有待处理的执行 job 时等待，不为凑进度重复派工。只有文本“下一轮另行派发”不算接续。一次性任务完成、目标期限结束或用户暂停时可以正常收尾，不能无限扩大发布范围。

当前宿主若返回 `SWARM_GOAL_NEXT_STEP_REQUIRED`，保留本轮已经发布和验收的事实，读取最新状态并补齐下一步，不重新发布、不另建成员。若目录实际提供 `swarm_goal_checkpoint`（Foundation 别名 `roami swarm goal checkpoint --input '<JSON>'`），确有能力、登录、资源或结果未知的失败时，用当前 `swarmId`、简短 `reason` 和本回合实际失败的 `failedToolCallId` 记录阻塞；猜错工具、参数错误或禁止操作不能当阻塞。该回执不完成目标，也不授予发布权限。

以实际工具目录为准；未上线的宿主不假称具有回复约束。等待未来排期必须有真实调度与到期回执；只写一个日期不能证明已经安排。Chrome/ADB 已走通的发布方式继续复用，不因缺少另一套 API 或 MCP 而重建发布流程。
