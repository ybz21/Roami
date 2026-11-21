# 创建任务时配置互审

- [设计总览（HTML）](index.html) 进入产品和技术设计。
- [产品设计（HTML）](product.html) 包含创建入口、按版本持续复审、用户故事和原型。
- [技术实现（HTML）](tech.html) 包含版本核验、复审调度、消息协议、轮次和兼容方案。
- [交互原型（HTML）](prototype.html?lang=zh) 演示初版开工、双会话和多轮审查；[新版状态示例](product.html#continuous) 展示通过后继续改代码的流程。
- [验收记录](acceptance.md) 记录初版实测、问题现场和持续复审的验收用例。

「互审」位于原工具条，点击后下方展开审查 Agent Logo 和交审方式。开工时创建 `review` 子会话，双方通过 `roami session send` 交审和回传意见。2026-11-21 改进提案将通过绑定到已审版本。后续变更进入「待复审」，沿用同一个 `review` 子会话。每批默认最多 3 轮。
