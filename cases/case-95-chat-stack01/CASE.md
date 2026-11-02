---
name: 多轮聊天约束叠加
description: 在完整多轮用户输入后逐轮检查回复、任务数量、归属、要求、修订和附件，区分聊天、续作及独立新任务。
---

本项含4段独立对话、18个用户轮次。合成中文/英文对话为公开输入，expect是宿主独立判定数据；fixture仅用于设施回归，不作为真实模型能力得分。

在源码根目录执行 `uv run --frozen --project agent-runtime python cases/case-95-chat-stack01/scripts/run.py --output .roami/rsi-conversations/chat-stack01 --mode fixture`。真实模型模式见tools.json和验收说明，使用节点保存的Main路由与Go统一准入；不运行真实后台执行器或生产会话。
