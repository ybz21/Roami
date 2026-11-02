# 多轮聊天新增标题字段被返回为布尔值

分类：真实 Main 模型的语义/结构化内容质量问题，尚未证明为通用代码根因。不是后台任务状态机缺陷；不应为本例在产品里硬编码标题值。

## 冻结复现

使用节点保存的 Main 路由、参数、图片能力和 Go 统一准入，在独立 Runtime/SQLite 中逐轮输入：

1. 先讨论海报，不建任务。约束为颜色蓝色、版式双栏、语言中文。只返回JSON，键为颜色、版式、语言。
2. 海报颜色改成绿色，双栏和中文保持。只返回完整JSON。
3. 取消海报的版式约束，删除版式这个键，其他已确认项保留。只返回JSON。
4. 海报再加标题一起阅读。只返回当前全部约束的JSON。

冻结合同期待第4轮为 `{"颜色":"绿色","语言":"中文","标题":"一起阅读"}`。两次独立真实回放均保留前两项，但把标题返回成 `true`，产生 `CHAT_CONSTRAINTS_MISMATCH`；任务数为0，没有误建任务。模型原始 tool/text 事件已包含错误值，宿主没有将字符串改成布尔值。

其中一轮先用reply传入标题null并错误填写requestCoverage=current，被正确拒绝后，模型改为answered却把标题写成true。不得通过放宽JSON类型或把首次拒绝当任务失败来掩盖语义问题。

## 证据和边界

- 固定案例：`cases/case-95-chat-stack01/input/conversations.json` 的 `chat-correction-and-removal`，第4轮。
- 独立判定：`agent-runtime/src/roami_agent/improvement/evaluation/conversation_oracle.py::grade_checkpoint`，JSON严格类型比较。
- 两轮原始记录分别保留在本机私有 `saved-main-full-v2` / `saved-main-full-v3` 中；只公开上述合成文字，不含私有历史、凭据或节点配置。
- 路由指纹一致，未知用量为0；这两次失败保留，不因后续单次通过而声称已修复。

## 建议

将本例纳入后续模型/提示策略的冻结A/B，对题意做独立核对；同时保留真实源数据、JSON类型与多轮约束测试。不能增加一次专用分类器或只针对这一个标题做字符串修补。当前新增Case和评测设施不宣称已解决该语义问题，后续真实复测与修复仍需跟踪。

最终source-bound-oracle-v4又复现同一标题错误；本轮三次真实完整对话诊断均在相同字段失败，未改写旧分数。评测设施与命令禁用修复通过 [PR #606](https://github.com/ybz21/Roami/pull/606) 交付，本质量问题不随该PR关闭。
