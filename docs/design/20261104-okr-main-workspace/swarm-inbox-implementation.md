# 群聊收件箱的实施边界

关联 #744，接续[通信设计](swarm-communication-design.md)与[协调契约](swarm-delivery-contract.md)。这是分批实施记录；完成条件仍是原宣传团队真正完成问题、答复、续派、验收与记忆交接，不能用某一批测试通过替代。

## 先建立真实消息与收件箱

`swarm_post` 保持原命令回执；新增可选 `kind`、`messageKey`、`replyTo` 和 `recipientMemberId`。缺省 `progress`，旧请求的字段与digest保持。真实作者、成员ID及task/revision/run从宿主绑定取得。业务键按Swarm/真实作者/原任务轮次分域；相同键同内容返回原post，改正文、kind或目标拒绝。旧命令重试继续原回执；不拿新run假冒旧run追加工作。

schema24使用独立 `swarm_post_routes` 保存新消息的路由与来源，不修改旧post正文、作者、回执或投递键。旧记录只按已知普通讨论展示，不根据人名补造历史身份或通知。`swarm_inbox` 在同一事务记录Main/稳定成员的待处理项；群聊、Main、成员都没有第二份业务消息。它属于平台协作库，与项目看板SQLite分开。

成员question/blocker/handoff进入原Main收件箱；同群定向消息同时指向原稳定成员。progress不唤醒。reply必须引用本群真实post；Main答复只解决它实际收到的对应项，并把回复指向原作者。成员答复不替Main完成独立验收。读回执与处理回执分开，读过但没有答复的问题继续待处理。没有自动终端注入，没有新的user消息。

`storage/swarm_inbox.py`负责稳定作者、业务去重、路由与收件箱；`dispatch/swarm_plans.py`保持受管fresh身份检查并在同一事务调用。`tools/swarm_catalog.py`、私有member-post入口和真实CLI保留新字段；Main/成员通过绑定入口读取各自收件箱，人的只读预览不冒充Main已读。快照只投影真实递送状态；页面不新增工具栏或内部ID输入。

## 随后接入宿主协调，不能偷换成user唤醒

协调批次另有宿主持久登记，绑定原目标委托、原Main、活动分支和冻结的message集合。`continuation`只是已有turn类型，不等于授权。Core的origin、PromptBuilder、reply来源审核、请求coverage及TaskRevisions均必须显式识别经过核验的批次，不能去取最近一条用户消息当授权。普通completion保护保留。

调度在Main空闲且未等待用户时，原子领取并建立批次/turn/job；等待用户要核对真实question与其后用户输入，不能只看turn=completed就判断空闲。新成员消息留下一批，Main回复不创建自身待处理。handoff和既有task.completion共用run结果身份，不能各创建一轮；正在执行的旧completion输入不被改写。

Main的后续指令与原用户委托分别保存。受限协调只继续同群原任务，仍经过最新revision/run、会话关闭、stop/unknown、workspace和具体外部行动授权检查。失败/重启保留原批次和消息，不换键重跑。来源遗忘、目标停止或委托撤销后失效，不复用旧授权。

## 分批验收与当前限制

先验证业务同键冲突、跨项目引用、旧run、新旧回执恢复、事务故障、读而未处理、Main/成员署名与定向回复；再验收调度、授权继承和handoff/completion竞争矩阵。最终用原Main与真实数据成员完成一项有用交接，经roami chrome核对页面与实际文件/来源，才关闭#744。schema24候选与后续协调均单独过门禁；没有部署或真机证据时不宣称具备线上能力。

[本批隔离验收](swarm-inbox-acceptance.md)。
