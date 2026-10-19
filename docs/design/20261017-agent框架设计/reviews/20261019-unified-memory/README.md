# 统一记忆入口

入口：设置 → 智能体 → 统一记忆（`#/settings/agent/memory`）。对话菜单中的记忆面板保留当前对话筛选，也提供统一记忆链接。手机继续使用首页、项目、工具、设置四个底部入口。

- 汇总当前节点、当前用户的有效结构化记忆；自动提炼与手动记住的内容使用同一管理入口。
- 支持全文字面检索，个人长期记忆、偏好、项目和日期筛选；对话内另有当前对话与任务筛选。
- 状态分开查看已确认、候选和冲突；保留候选确认/拒绝、删除记忆与彻底忘记。
- 每条标明类型、适用范围、更新时间及来源数量。来源弹窗可打开原始对话、分支和消息。
- 每页 20 条，显示总数，支持前后翻页。不同范围的条目不按召回规则合并。
- 新增 `GET /v1/memories/catalog`（Go 鉴权代理为 `/api/agent/memories/catalog`）；无数据库迁移，无自动范围提升，原有召回与删除/忘记机制保持。

## 自动检查

- `scripts/dev/quality/check.sh full`：Go、Python 533 项、前端 typecheck/i18n/hover/build 通过。
- `uv run pytest tests/test_memory_catalog.py -q` 四项通过，覆盖每日记忆和任务名称。
- `npx vitest run`：91 文件、663 项通过。
- 管理查询覆盖跨对话汇总、个人/项目/对话/类型/状态筛选、分页、字面标点、owner 隔离、过期和删除排除；自动偏好回归覆盖彻底忘记后的派生条目排除。
- 界面用例覆盖旧请求晚到、翻页后搜索重置、个人筛选、统一入口和定位原始消息。

## 浏览器与真机

验收使用独立实例，23 条有效记忆和 1 条候选均为测试数据。正式记忆与专业智能体会话不参与写入、删除或发消息测试；测试数据通过运行时的记忆写入逻辑生成。

桌面 Chrome 中英文与 Redmi Note 8 Android Chrome 均通过（[结构化验证结果](verification.json)）：

| 场景 | 实际结果 |
|---|---|
| 设置列表进入统一记忆 | 显示跨范围 23 条有效记录，首页 20 条；标题及筛选完整，无横向越界 |
| 真滚动与翻页 | 桌面滚轮、手机触控手势均能滚动；文档本身不滚动，下一页显示剩余 3 条，可返回 |
| 个人范围与来源 | 仅保留 1 条个人偏好，来源原文正确；跳转到历史对话的原始分支与消息，不被主对话重定向 |
| 搜索与候选 | 搜索“项目技术栈”仅 1 条；可单独查看候选；桌面确认候选并删除该测试记忆后，查询结果归零 |
| 手机导航 | 二级页返回以及首页、项目、工具、设置四项均由 Android 实际触控验证；底栏可达；原对话菜单到统一记忆的触控路径也通过 |

第一轮来源跳转失败由验收任务 fixture 缺少 `executor` 字段导致，补齐后通过；手机第一轮脚本误将内容行而非外层滚动容器作为手势边界，修正后通过。上述两次均保留失败输出，未据此修改产品的任务或滚动架构。

截图只含独立验收数据，发布在 PR #329 的 `pr-shots` 孤儿分支：

- [桌面修改前](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-memory-before-desktop.png) / [桌面修改后](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-memory-after-desktop.png)
- [Android 修改前](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-memory-before-phone.png) / [Android 修改后](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-memory-after-phone.png)
- [Android 来源弹窗](https://raw.githubusercontent.com/ybz21/Roami/pr-shots/pr-329/roami-memory-source-phone.png)

