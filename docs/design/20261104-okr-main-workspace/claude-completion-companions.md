# Claude 完成回调的 Skill 与图片伴随记录

## 产品设计

原 X 成员已在原输入中返回平台帖子与公开读回材料，原生界面也已结束；宿主仍为 running/unknown，9 个安全分类器拒绝的 Bash 调用留在 pending。正式 reconcile-session 返回 SESSION_RECONCILIATION_STOP_UNCONFIRMED，所以 Main 仍被同项目目录的写入保护挡住。不能凭终端空闲清状态，也不能把成员发布声明当成独立验收。

本轮沿用既有“完整原生记录 + 实际进程停止 + 原目录写者 + 二次来源核验”的完成对账入口，修正它未识别的标准记录，使原 Main 自动收到真实执行结果。

## 用户故事

- 原成员加载项目 Skill、读取图片并交付后，宿主能识别完整结束，不要求用户再催或重开实例。
- 工具前置失败有对应的原生 tool_result 时，不永远被当成仍在执行。
- 仍有后台任务、未配对工具、其他输入或阻止续接的 Stop 时，继续保持未知与目录保护。

## 技术设计

旧完整记录解析器只允许七种同步工具，Skill 被当成未知异步工具；它也拒绝原生 Skill 展开和图片尺寸提示的 isMeta 用户记录。当前真实记录同时包含这些形态，不能靠放行所有 isMeta 或将 Skill 一律改成同步解决。

只在完成对账解析器新增受约束的伴随记录识别：

- Skill 调用必须有正常默认输入、同一原生根输入、完整 tool_result，以及 SDK 的 success/commandName 元数据。之后必须看到同一根输入中 sourceToolUseID 指向该调用的直接 Skill 展开记录，isMeta 与 turnCompanion 均为真。未展开、fork/后台或未知工具继续拒绝，不扩展中断对账的工具白名单。
- 图片尺寸提示只接受 SDK 的精确尺寸格式，且同时是 isMeta/turnCompanion；其父链必须只经附件回到一个已完成 Read 的原生 image 结果。普通文本、无对应图片的提示和其他 prompt 不能冒充伴随记录。
- 仍要求完整工具调用/结果配对、当前 provider/prompt/精确正文哈希、项目内目录、完整未阻挡的 stop_hook_summary、无后来输入/工具，并经原有进程与目录写者证明后方可生成结果。伴随记录不提供发布批准或任何新权限。

复用现有 Go ReconcileSession 与 Python 原生监控的有限退避。不增加第二个轮询器，不把读取诊断或终端空闲当停止证明，不直接改生命周期文件、数据库或 busy。

## 验收

先用隔离记录复现旧拒绝；覆盖默认 Skill 与 Read 图片、缺失/错配结果或来源、fork/后台、旧 prompt/provider、普通 meta、阻挡 Stop、后续输入与活动进程。再用候选解析器只读原 X 记录，确认返回的工具集合覆盖原 9 个 pending 调用，并保留真实来源摘要。正式生产对账只在代码完整检查、PR/CI 与对应发布产物核验后执行。

平台发布和数据入账仍由原 Main 独立验收，本设计不声明它们完成。

## 本地验证记录

默认 Skill、图片提示、fork/错配/缺失来源、阻挡 Stop、后台调用、原实例前轮 Skill 与原有缺失工具钩子的进程/目录专项通过。候选对原 X 记录只读解析得到 114 个工具结果，覆盖原 9 个 pending，真实进程检查为已停止；未写生产状态。

完整检查通过：Go 全套、前端 typecheck/i18n/hover/生产构建、Secret scan 与 staged file policy；按实际 Go 差异跳过 Python runtime/Skill 全套，保留 Go 所需 Python harness。首次全量的既有 quota owned_child 进程证明失败，未改源码，在独立进程组与私有测试实例中先复验该用例、再重跑完整检查通过；没有放宽证明或跳过失败。

这仍是代码和候选只读验证，正式生产对账、原 Main 独立验收和业务循环尚未完成。
