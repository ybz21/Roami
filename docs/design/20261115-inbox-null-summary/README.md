# 消息空摘要崩溃修复

## 问题与预期

消息列表包含 `summary: null` 时仍应展示标题和时间，支持打开来源、标为已读；
有摘要的消息继续展示原有预览。不新增文案或改变布局。

## 根因与实现

报错包 `index-Ce5A_f1N.js:134:36090` 的 `QS` 对应 `AgentInbox.tsx` 的
`noticePreview`，调用点为消息列表的 `noticePreview(n.summary)`。
`notification_pages.py` 从消息内容提取文本，缺少文本时 SQL 表达式返回 `NULL`。
默认参数 `text = ''` 仅处理 `undefined`，因此 `null.replace` 抛错。

`AgentNotice.summary` 明确允许 `null`；预览先用 `text ?? ''` 归一化，保留原有
Markdown 链接和格式清理。服务端数据和已读水位逻辑不变。

## 验收记录

- 回归用例先在原实现复现相同异常，修复后覆盖 `null`、缺省、空字符串，以及混合的正常摘要。
  每种情况均验证消息可打开、按实际水位标为已读。
- 消息列表测试 11 项通过；前端全量 Vitest：255 个文件、1861 项通过。
- `quality/check.sh quick` 和 `full` 通过，包含类型、国际化、hover 检查与生产构建；
  本次仅改前端及文档，按改动范围跳过 Python 和 Go 检查。
- 浏览器使用真实 `AgentInbox`、主题、i18n、样式和 API Hook，网络响应使用隔离测试数据。
  桌面 1280、1920、2560、3440 CSS px 验证无异常、无横向溢出、消息可命中并打开。
- Redmi Note 8：392 CSS px、`compact` / `coarse`，通过 LAN 加载同一组件；真实触摸事件
  打开消息，触摸滚动使列表 `scrollTop` 从 0 增加约 299px。中英文与深浅主题均检查。
- 修复前桌面和手机均显示相同 `null.replace` 错误；修复后摘要为空但标题、时间和正常摘要可见。
  这是组件回归验收，未声称重新验收整套应用导航和键盘流程。
- 原始日志中的 404 未提供资源 URL，无法归因；本次修复准确对应所给 JavaScript 堆栈。

截图随 PR 存于 `pr-shots` 分支，不提交到主分支。
