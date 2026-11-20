# 创建任务时配置互审

- [设计总览（HTML）](index.html) 进入产品和技术设计。
- [产品设计（HTML）](product.html) 包含创建入口、审查流程、用户故事和原型。
- [技术实现（HTML）](tech.html) 包含会话启动、双方 Prompt、消息协议、轮次状态和代码落点。
- [交互原型（HTML）](prototype.html?lang=zh) 演示开任务、两个 Agent 终端和多轮复审。
- [验收记录](acceptance.md) 记录桌面、Android 和隔离会话的实测。

「互审」位于原工具条，点击后下方展开审查 Agent Logo 和交审方式。开工时创建 `review` 子会话，双方通过 `roami session send` 交审、回传意见和提交修复。默认最多 3 轮，通过即停。
