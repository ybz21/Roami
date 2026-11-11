# Claude 首次模型失败的可信收口

## 产品设计与用户故事

同一 OKR 的 Claude 数据分析首个请求被模型网关拒绝时，应保留原实例和记忆，以明确失败结束本轮，让运营等成员继续；修正模型绑定后仍向原 provider 续派。失败不算任务完成，不自动重试模型，更不重放发布。报错截图只能用于诊断，不能作为停止证明。

## 技术设计

官方 StopFailure 表示 API 错误结束当前轮，但该回调可能缺少 promptId，现有宿主因此保守记为 unknown：[Claude Hooks reference](https://code.claude.com/docs/en/hooks#stopfailure)。新增只针对新 provider 第一个 prompt 的首个响应、没有任何工具调用的 provider 失败证明：

1. 使用原生 session/pane/PID、providerHome、provider ID、当前 launchKey 和 prompt ID/hash 定位唯一、同属主、不可公共写入的有界 transcript。
2. 本轮 user 必须匹配宿主保存的原始 prompt，前面不能有任何用户/助手历史或压缩边界，避免既有会话的定时任务与旧工具活动被遗漏；之后只能是上下文与请求元数据、一个 synthetic API error（明确 failedResponseHadNoToolCall、零 token）和指向该 error UUID 的 turn_duration。已有正常回复、工具、子链、后续用户输入、错目录/会话或不完整/变化文件一律拒绝。
3. 保持现有进程停止证明，拒绝未完成工具和身份变化。证据成立后由正常 CLI status 协议写入带 SHA 的 completion-source/result，状态为 failed；有正式取消请求时为 cancelled。保留 provider 与物理会话，不修改任务数据库、busy、模型路由、密钥或费用。
4. 重复读取复用已落盘回执，不重新派发。一般的中途 API 错误不走此分支，仍保持 unknown，避免把已经发生的外部动作误判为未执行。

## 验收边界

需覆盖真实生命周期、同实例续派、缺/错 prompt、已有工具或普通回复、后续消息、错误 parent UUID、缺失结束记录、非 synthetic/非零 token、侧链、可写/替换文件及未停进程；保留现有 Claude Stop/idle 和 Codex 全部证明规则。真实项目只通过正式 CLI 读取原 launch key 核验，不手写状态文件或终端文字回执。

## 原生手工输入后的显式对账

自动 status 仍拒绝本轮之后任何新用户输入。若用户在原实例执行 `/model`、随后继续，旧轮的输入已经改变，必须使用现有 `execution reconcile-session` 显式对账入口：核对从宿主原 prompt 起每个普通请求都只有首次 synthetic 拒绝及匹配结束记录，没有工具或普通输出；`/model` 只接受 provider 记录的完整本地命令三联（meta caveat、同 promptId 的 /model 命令、stdout，UUID 父链一致），不接受其他命令或未结束输入。

显式对账保留现有会话/进程/工作区 writer 租约、上下文与两次稳定证据校验，统一记为 SESSION_SCOPE_CHANGED_STOPPED 失败，不作为原任务成功。待执行请求、任何普通响应或工具、模型请求超时/5xx、错身份与活跃进程一律继续拒绝。只改变正常宿主回执与状态机，不直接修改业务数据库或 busy。

## 显式取消时处理本轮新增子进程

真实实例还存在首次绑定后启动的 MCP 子进程，纯停止证明会正确拒绝收口。显式取消新增一条窄路径：仅当上面的无工具 API 拒绝窗口成立、宿主绑定/当前 pane/PID 出生标识/进程域一致且无待执行工具时，捕获本轮新增、确属该 pane 后代的进程；沿用已有 pidfd 取消机制，只停止捕获的 PID+出生标识，不发送新 prompt，不处理 provider 或原有基线/其他会话进程。

信号前保存与窗口 SHA 绑定的取消日志；信号结果不确定时不重放，不扩充新目标。日志只证明停止请求，不证明进程已退出。正常 status/显式 reconcile 仍必须重新确认实际停止后才落完成回执；Claude 实例、会话和记忆保留。此路径只由正式取消调用触发，不在只读状态查询中清理进程。
