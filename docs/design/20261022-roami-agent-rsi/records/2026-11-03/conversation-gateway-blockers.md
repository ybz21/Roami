# 多轮会话验收保留网关阻塞原因

对应问题：[#609](https://github.com/ybz21/Roami/issues/609)。

## 产品设计与用户故事

用户先看运行汇总，需要分清模型完成后答错和模型根本没有执行。2026-11-03原始CHAT-STACK01单场景复现：Go因共享账本存在未知用量而拒绝准入，Agent正确停止；验收却把空答案记为`CHAT_JSON_REQUIRED`，顶层`failure=null`，并宣称已测试真实模型语义。

汇总应显示真实网关错误及阻塞数量，详情保留每个回合是否完成内容评分。先前已经验证的回合不能因后续阻塞消失，真正的JSON或字段类型错误仍须失败。

## 技术设计与模块

- `improvement/evaluation/conversation_scenarios.py`只在真实Runtime回合`completed`后调用原内容oracle；失败回合从本回合计量日志提取真实传输错误。可信`ModelAdmissionRejected`标记阻塞，不通过模型文本识别或推测准入。
- 每个检查点增加`semantic_checked`、`state`和`failure`，场景增加`state`。原`passed`布尔值保留；未执行不是通过，也没有虚构内容分数。
- `scripts/dev/run-conversation-scenarios.py`将嵌套场景错误带入顶层，保留驱动异常优先级，增加阻塞/失败场景数、已测语义回合数及实际语义覆盖说明。
- Agent传输层已经正确遵守Go拒绝，本次修改验收归因层。未新增Python准入、用量上限、模型配置或自动重试；不清理未知账本，不假定401零费用。

## Case与验收

[Case100 / MECH-CG01](../../../../../cases/case-100-mech-cg01/CASE.md)提供name、description、公开控制输入、工具、来源、统一runner和验收合同。9项独立检查覆盖三种可信准入拒绝、先通过后阻塞、真实错误JSON/null、模型文本伪造网关错误、未知用量传输失败和驱动错误优先级。零真实模型调用；不纳入历史40/60项。

本次定向会话检查46通过；Case100独立runner9通过、零跳过，冻结前后一致、隔离实例清理成功。首次runner因对venv解释器做`resolve()`而落到系统Python导致依赖未找到，已改为保留venv路径；失败回执保留，不计为生产缺陷。

沿用节点保存配置重新执行原`chat-correction-and-removal`场景，原合同SHA256仍为`f3ab4f67aebe81cad43467d7c6f737e4db41c1970550045fdacf730472d88529`，路由指纹仍为`9f70c28403cf6bac4b1017cc65aa7b6eafa4ed83c3ea55a1d8c674b3ac8b3b29`。结果正确显示`MODEL_PROXY_USAGE_UNKNOWN`、阻塞1、内容失败0、已测语义0、外部请求0、已知用量0，源码冻结一致、清理成功。此次没有调用上游模型，不能证明#605字段输出已修复。

工程quick已通过：Python3145通过、48项环境相关跳过；Go、i18n、hover、类型与扫描通过。既有Go进程观察检查在原作用域出现失败，保留回执；独立作用域连续20轮通过，生产停止保护未改动。full、提交钩子及CI的最终结果以PR回执记录。#605、股票/PPT与音视频质量、独立校准、正式全套和真实观察仍未通过；本次不关闭这些汇总问题、不改历史成绩，不部署或启用日程。
