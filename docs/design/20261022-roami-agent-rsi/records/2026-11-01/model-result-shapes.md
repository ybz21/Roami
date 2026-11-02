# 错误模型JSON的动作隔离与队列续办

## 产品设计与用户故事

用户需要后台复盘失败后仍能看到失败原因、已有用量和后续任务进展。模型返回合法JSON数组、null或其他非对象时，复盘/Issue计划直接取字段，AttributeError穿过ResearchWorker已有异常边界，整个后台任务退出；当前动作仍running，下一动作未处理。

## 技术设计

在既有消费边界校验形状：批量观察、周期报告、Issue计划先验证JSON对象；证据读取请求列表逐项验证对象；Codex回执先验证事件及事件类型、item和用量对象，再使用字段。沿用既有领域错误码，交给ResearchWorker既有block流程，不增加吞掉编程错误的全局异常捕获。

正常身份、结束事件、单结果、禁用工具和用量规则保持；模型配置、重试、Go每日准入、原评分/阈值及历史数据保持。源代码在RSI领域与工作流输入边界，不向Agent核心增加业务能力。

## 复现与验收设计

旧实现35项失败。直接Worker.execute收到脚本模型的[]后抛AttributeError，动作保持running；回执已经保存，含120个合成Token。修复验收使用真实ResearchWorker调度和私有SQLite，验证失败动作blocked、下一动作继续处理、Worker仍活着，恢复同一动作复用原回执而不重放。Case86提供实际读取的公开错误JSON样例、工具、来源与冻结运行器，机制验收不算真实任务质量。

18份已有Codex进程回执均为合法单对象输出，没有复现多消息问题，本次没有改动单消息协议。官方JSONL与最终结果的说明见[OpenAI Docs](https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable)。不能将本次合成复现认定为历史红色报错的全部根因。

完整门禁、Case86和最终源码一致性结果随后补录。Worker图片开启、独立双模型评分、人工参考、音视频和股票完整质量、正式60题及两次真实完整日观察仍未完成，#443/#445/#446保持开放。

## 最终验证

Case86为35项通过、零失败/跳过；定向94项通过，包含实际Codex CLI经过脚本化网关的既有协议检查；目录17项通过，总目录85项（序号到Case86，历史缺号保留），原混合套件40个自编Case与正式60项不变。旧实现35项失败，独立Worker.execute确实抛AttributeError且动作留running；新真实异步队列处理下一动作，坏动作blocked，回执[]和120个合成Token保留；显式恢复后脚本模型调用仍为1。这里的模型和计量全是协议夹具，未调用真实模型，也未生成新任务质量成绩或人工标签。

quick/full各3002项通过且零跳过，Go、前端静态检查/构建和扫描通过。冻结v169镜像203核心文件与v160相同，136可信文件中只有3处边界校验变化；14迁移与7条退役路径核对，151项Runtime输入（含新增公开JSON夹具），本轮实际执行1851通过/12环境跳过。初次运行器沿用150项旧输入数量的断言、目录计数未同步，以及迁移旧验收目录导致隔离器拒绝接管旧socket，均保留日志并修正；通过原记录在同一路径校验已拥有实例后，最终Case使用新的隔离目录，没有采用未记录socket或触及用户tmux。

节点模型、参数、图片能力、重试、限额和四份配置哈希保持。候选仅准备，未部署、未安装节点Skill或启用日程；临时源分支和worktree在合入后清理。详细节点证据：model-result-shapes-evidence-20261101中的old-worker-crash-proof.json、old-regression.xml、targeted.xml、case86-final、catalog.log、quality日志及frozen-runtime-proof.json。原音视频/股票质量、独立评分、人工参考及正式全套/真实完整日观察仍待完成，相关汇总Issue不关闭。
