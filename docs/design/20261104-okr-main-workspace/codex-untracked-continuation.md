# 原 Codex 续派在压缩后的可信执行恢复

## Product Design

原X成员本轮已完成设备核对并明确报告PIN锁，但宿主仍显示preparing/unknown。恢复必须让Main看到本轮真实阻塞并在资源恢复后续派同一任务；不能用屏幕文字、发布文件或手写任务状态证明完成。设备PIN仍须持有人本地解锁，不获取或猜测凭据。

## User Stories

- 原成员在已有长会话里压缩后继续，生命周期回调缺失时，宿主从真实原生执行记录恢复本次结果，不重复输入。
- 相同会话里的旧结果、其他线程、新人工输入或未结束工具不能当作本轮完成。
- 真实设备阻塞不变成已发布，Main得到准确阻塞后保留原业务键和原实例。

## Technical Design

实际轮次r27的启动记录为01a1c44e-75bd-7883-9145-14270f1b19c4，原provider不变；其task_started、compacted、完整委派UserMessage、工具结果和task_complete均在原rollout。宿主lifecycle仍持有旧turn，SESSION_START_UNTRACKED导致现有按旧turn读取的完成核验不命中。

仅在同原provider、同session/resource、同launchKey、当前spec精确prompt摘要相符且明确缺失启动跟踪的范围内，发现真实文件末尾的终结turn，再用现有严格解析验证完整prompt、根turn、工作目录、已结束工具和最终答复。新turn启动和结束必须晚于本次不可变spec落盘；拒绝取消、旧终结、未结束进程、后续人工输入、其他provider、文件歧义/替换/不安全权限。不接受文件自报业务成功作为授权。恢复原始记录摘要，沿用宿主已有结果与任务观察入口，不直接写Python数据库、busy或账目。

## Acceptance

隔离fixture覆盖缺失启动回调后的已知终结、压缩后原prompt；旧turn、启动早于spec、错误prompt/provider/目录、歧义文件、手工追加输入、未结束工具/进程和取消均不得误判。生产只读先复现并核对摘要，代码经Go专项/full/正常提交/PR后才部署，部署后通过原任务观察证明恢复。不将该恢复称为X发布成功。


## 具体实现与实际只读验证（11月11日）

原r27之后还出现真实人工补充输入与新执行轮，不能把最新答复冒充原任务成功。实现扩展显式 reconcile-session 的保守失败收口：仅接受SESSION_START_UNTRACKED、原scope和空待结束工具集；从当前不可变spec推导精确委派prompt与时间下界，要求在同一可信provider记录中只匹配一次，后续原生回合全部有终结、最终答复与工具收口。只产生failed/SESSION_SCOPE_CHANGED_STOPPED、InputStopped和OutcomeKnown；不宣告平台提交成败。原文件已超过旧64MiB检查上限，该专用读取保留256MiB文件和读取硬上限，流式解析；超限继续明确未知，不能静默截断或仅信尾部。未来可另做可核验启动游标，避免长历史重复扫描。

锁定原会话/进程、workspace writer、两次相同证据和宿主既有去重账本后才提交停止回执。取消请求不变成发布成功，后续仍由原Main读取真实回执并受管续派。启动 hook 缺失的新成功回合不自动成为可信业务结果。

实际记录只读复验通过：原委派输入、原provider/工作目录与完整终结链一致，摘要005a7f72dc66baec8dd4571f7fbdfac946cc5f87bb2852004c0dc78924129a6f，原生终结1794330622694；未调用恢复写入、未碰手机或状态库。日志 /tmp/okr-codex-recovery-actual-readonly-20261111.log。该临时复验文件不进仓库；生产恢复须等PR检查、合入及部署。


自动观察也复用同一保守停止核验：Status只在原scope、原launch、确定的漏跟踪原因和零待结束工具条件下运行；不得只提供一个需要人反复执行的恢复命令。成功核验结算failed，已有取消请求结算cancelled，两者都保持原平台事实未知。跨回合证据不冒用旧turnId，写原launch的停止摘要；现有Python观察器据此处理原pending steer/依赖，不增加新调度器。显式reconcile-session保留兼容的人工恢复入口，使用同一证据读取。
