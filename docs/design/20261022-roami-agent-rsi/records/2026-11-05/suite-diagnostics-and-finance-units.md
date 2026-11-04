# 当前套件的默认诊断与财务单位合同

续 [PR #662](https://github.com/ybz21/Roami/pull/662) 与 [PR #664](https://github.com/ybz21/Roami/pull/664)。新完整基线 43 通过、11 失败、6 待评分保持；没有解决全部 RSI 问题。

## Product Design

更换合法抽样题后，界面的默认诊断仍应选择当前冻结套件里的十项，而非固定某个旧公共数据 ID。金额结果需要说明采用哪组源数据的单位，不能同时禁止单位文本却让模型猜是否换算为另一张表的单位。

## User Stories

- 新 FinQA 样本替换矛盾标注后，默认诊断不再报 Case 找不到；仍有九项固定机制/业务检查和一项财务样本。
- 显式点选、原运行复测、幂等请求和历史快照继续使用原 ID，不悄悄换题。
- 文本中以百万计的金额不因无关表格以千计而换算；百分数比例和原 0.0001 精度合同保持。

## Technical Design

`evaluation/diagnostic_selection.py` 按当前冻结套件的 origin.benchmark=finqa、public_component 层选择排序首项；不依赖 ID 前缀或参考答案。选择发生在 `enqueue_diagnostic_request` 既有事务内，先校验注册文件哈希，再校验完整十项均存在，之后才写队列与运行。缺少覆盖不静默减题。`pipeline_runner` 仅在未指定 case_ids 且没有 baseline_run 时使用默认选择；显式空/非法列表继续拒绝，既有评分准入保持。

`sampling.import_finqa` 保留原数据、seed、分层抽样、矛盾标注排除、参考值和阈值；单轮说明增加通用金额单位约定，不换算为基本货币或无关表格单位。新命名空间为 finqa-sample-v3 / financial-numeric-v3-source-units，ConvFinQA 原合同保持。没有问题 ID、样本数值或答案专用分支，不把参考或程序给模型。

## 验收证据

旧源码加载同一组检查为 2 failed / 9 passed：新样本及替换样本失败，原固定样本控制通过。修复后的新目录/入队、原重放与财务导入检查共 90 项通过。覆盖更新样本、旧样本、稳定选择、缺少覆盖零部分记录、显式选择/原快照不注入默认项、非法值不降级，以及注册文件变更。

保存节点 Main/Worker 路由、参数及能力，使用同一来源绑定镜像独立实模三道有效样本：v2 为 2/3，v3 为 3/3。v2 失败的金额为 916000，原判定为 916；新约定说明相关金额自身单位后通过。源报告、抽样 ID、预期值、0.0001 阈值与执行限制逐项相同；两个合同不同，不能宣称同合同提分，不能改写旧完整运行。两组三题的全部 52 个不同 gatewayCallId 逐笔匹配本地 Go 权威回执：52 known / HTTP 200、194,334 tokens、0.10761 CNY，无缺失；旧未知账目保持。

固定官方数据 SHA256 与既有抽样锁相同。租金旧标注 answer=215.33、exe_ans=324.5 矛盾，既有 v2 导入器按原 seed 排除；PMI 旧题为 -0.538 与 +0.538 的方向差异，不能记作舍入。原失败与来源绑定之前的排队确认误取分别保留。

线上套件曾由 v18 切到已验证参考的 v19；发现旧默认诊断仍固定旧 ID 后，已通过带 revision 的偏好 API 恢复 v18（6→7），其余偏好不变、enabled=false。v19 保留注册用于显式独立验收；待本修复部署后再选择新合同。没有排队生产诊断、清理历史账目或绕过升级 busy。进一步只读核对：Python running jobs 为 0，三个 CLI 回执均 unknown，分别为 SESSION_BINDING_UNAVAILABLE、SESSION_START_UNTRACKED、SESSION_COMPLETION_MISMATCH；逻辑任务仍为两项 running、一项 cancelling。两个会话存在、一个已不在列表，但这些观察都不构成可靠的结束/写入结果证明，未停止其他工作或改写任务状态。

修复后的默认选择另与准备好的 v20 完整 60 项合同实际组合核对：十项检查完整、默认诊断十项唯一且全部存在；v20 未注册或切换为生产选择，也未执行新完整 60 项。

另以冻结原场景核对 #635：三轮均正确先询问歧义、再只修订周一任务，9/9 轮检查；18 笔调用逐笔匹配 Go known / HTTP 200，77,111 tokens、0.026157 CNY。后台为 synthetic_checkpoint，未改 Main 指令，不证明因果根治或线上交付，旧失败保持。

现有线上宿主 main-b240588e 配合来源绑定镜像的原 FinQA 题独立通过：8 笔 Go known / HTTP 200、25,846 tokens。此处验证镜像与旧宿主兼容。完整检查通过且确认无 queued/running/cancelling 的生产 RSI 请求后，已把默认 roami-rsi-eval:local 切为已通过 #664 验收的来源绑定镜像 2dded6ed…；旧 ff250e9b… 保留在 roami-rsi-eval:before-bound-answer-20261105。模型设置逐字保持、没有服务重启、套件选择或旧分数更改，也不称为模型策略晋升。

最终冻结源码的 full 全部通过：Python 3458 passed / 48 环境跳过，Go、i18n、hover、typecheck 和生产构建通过；640 份运行时/测试/检查文件无漂移。提交钩子 quick 通过后才生成源码提交；最终输出保留在 PR 验收截图和本机原始日志。证据见 [suite-diagnostics-and-finance-units.json](evidence/suite-diagnostics-and-finance-units.json)。
