# 对话中的本机文件链接

## 产品设计

历史任务回报把交付物写成 `/home/ai/.../index.html` 等绝对文件路径。
原先对话直接把该路径作为网页地址，命中应用外壳，无法看到交付物。
现在识别常见 Linux / macOS 文件根目录，通过已有的 `/api/file/<绝对路径>` 文件入口访问。
沿用现有桌面新标签和手机全屏预览，不新增页面或文案。

## 用户故事

- 用户点击历史回报中的 HTML 或图片，直接看到对应文件。
- 手机预览支持真实触摸滚动，返回后仍停留在原对话。
- 切换当前节点后，消息中的文件仍从消息所属节点读取。
- 外站、显式节点地址、API 地址、应用导航与下载参数保持原有语义。

## 技术设计

`agent-resource-url.ts` 统一转换常见文件根目录的绝对路径，并通过 `nodePath` 绑定消息来源节点。
`AgentMessageView` 与 `NativeConversation` 已共用该解析器，Markdown 图片也复用同一入口。
保持路径、已有 URL 编码、查询参数和片段，HTML 的同目录相对资源继续由路径接口解析。
不增加后端路由、轮询或布局样式。

## 验收记录（2026-10-30）

- 回归测试先在旧实现失败（6 项），修复后通过。
- `npm run typecheck && npm run i18n:check && npm run hover:check && npx vitest run && npm run build` 通过；147 个测试文件、1,103 项测试通过。
- `scripts/dev/quality/check.sh quick` 与 `scripts/dev/quality/check.sh full` 通过；无 Python 源码、依赖或配置变更，按规则跳过 Python 检查。
- 隔离实例通过 `scripts/dev/isolated-roami.sh /tmp/roami-file-link-009n ...` 启动；验收夹具使用真实 AgentMessageView、Markdown、MobileFilePreview、FileView 和文件接口。
- 桌面对话生成正确的文件链接；HTML 文件入口显示完整正文及 18 条来源链接，桌面图片为 1440×1000，已解码。
- Redmi Note 8：392 CSS px、DPR 2.75、compact/coarse，HTTPS 经 LAN 访问。ADB 真实点按打开 HTML，iframe 有正文、高度 681px，无横向溢出；真实滑动后 scrollTop 从 0 变为 585px。
- ADB 点按返回栏及系统返回均回到原对话；两张图片分别成功解码为 1440×1000、390×3100。
- 隔离服务、临时前端夹具、测试标签页及本任务的 ADB 转发均已清理；未更新用户当前运行的服务。

旧的绝对路径在桌面与手机均命中 Roami 空白工作区，确认未展示 HTML；已补录改前截图供 PR 对照。

验收截图保留在本机，并在 PR 中上传至 `pr-shots` 分支，不提交一次性图片到主分支：
[桌面 HTML](/api/file/tmp/file-link-desktop-after.png)、[手机 HTML](/api/file/tmp/file-link-phone-after.png)、[手机图片](/api/file/tmp/file-link-phone-image.png)。
