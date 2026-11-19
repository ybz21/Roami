# 原生工具诊断的宿主记录

## 产品设计

持续目标的 Main 需要区分模型/工具曾经出错、现在是否阻塞、输入是否停止和业务是否完成。Go 已从绑定原生记录提取工具前置分类失败，但 Python 丢弃 reportedToolError，Main 和后续监督没有可持久引用的来源。本轮补这一条诊断记录链路，沿用原实例和任务；产品展示与自动恢复仍需后续独立实现。

## 用户故事

- 原成员发生已识别的原生分类错误后，后续读取能找到真实时间、工具、来源摘要与原轮次。
- 成员后来成功继续时，旧诊断保留为历史，不把它显示成当前仍被阻塞。
- 新 run、其他项目或已更换 provider 不能借用旧诊断作为恢复依据。诊断不产生批准、停止或发布结果。

## 技术设计

复用 CodingExecutor 的现有 status/poll；不增加轮询器。Go 负责原生文件、当前 provider/prompt 和摘要的提取及来源核验。Python 只接受当前 CLI 回执中的已知 source/code，并核对原 task/run、已记录 provider/session、项目工作目录边界、时间及有界字段。路径接受已绑定项目内子目录，拒绝相对目录与项目外位置；回执省略 workspace 时仅使用同一 run 已记录的正式 workspace。

storage/native_tool_observations.py 保存 task.execution_tool_diagnostic 事件，以原 run/sourceDigest 去重，相同摘要却不同内容报冲突，不覆盖既有记录。内容只保留结构化诊断字段，不保存原命令、错误全文或凭据。事件包含原 revision/run；读取同时校验 task/run/revision，并按提供者记录时刻选最新诊断，迟到旧观察不盖住新观察。

任务详情的原 attempt 增加 toolDiagnostic；Main 的 task_status 仅在 includeResult=true 时补 executorToolDiagnostic。返回真实 eventId、diagnosticOnly=true 与 reported 字段，默认轻量状态不加入旧错误。旧 run 在历史详情仍可追溯，当前新 run 不继承旧诊断。工具目录明确它是历史观察，不代表当前阻塞。

记录诊断不改变任务结果、停止标记、忙闲、授权、模型或费用，不生成 verify/yield/新 Main job。缺少新报告也不意味着错误已恢复；恢复需要另外的真实观察。eventId 是宿主诊断来源，不是 failedToolCallId，不伪造成注册能力调用或成员问题。

## 下一步与恢复准入

#979 的监督应先对账已有停止结果，再根据当前原目标与最新轮次检查观察是否仍然适用。历史最后一次失败不足以取消输入：需要当前来源核验、新活动/成功结果、原生等待或显式成员让出等额外证据。健康长任务不因时长被停止。任何受管停止都需真实输入停止证明才能交回原 Main；平台结果未知沿用原业务键只读对账。相关持续性与产品设计见 autonomous-operation.md，#982 在诊断自动恢复链路完成前保持开放。

## 验收

结构化来源与字段边界、目录逃逸、原 provider/session、重复/冲突、迟到观察、run/revision 隔离、轻量状态不带历史诊断、原任务详情和 Main 显式读取均需覆盖；有错误记录也不产生结果、产物或恢复 job。当前专项与既有进度/执行器组合61项通过。完整门禁、PR、生产记录和原 Main 恢复仍待核验，不能据此宣布自主运营完成。

只读生产观察补充：原 X 新轮次出现两次分类失败后，后续工具结果继续成功。正式 Go status 仍保留较早的 reportedToolError，state=running 且没有最终 result。这直接说明该字段不能当作“目前卡住”或自动停止许可；本实现保留它的来源/时刻及 diagnosticOnly 语义，没有控制该原执行。原始记录保留在本机私有验收目录，不发布原命令或账号凭据。

完整门禁通过：Go全套、Python5182 passed / 48 skipped / 6 subtests（1503.48秒）、前端typecheck/i18n/hover/生产构建及扫描。完整检查期间只补充设计与只读观察记录；提交前比较冻结树确认运行时代码未变，再运行quick与提交钩子。尚未部署本诊断接入，自动恢复控制器与产品状态投影仍未实现。
