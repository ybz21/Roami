# 验收记录

日期：2026-11-19。改动只涉及顶部工作区标签的公共选中样式。

## 运行环境与视觉检查

- 通过 `scripts/dev/isolated-roami.sh /tmp/roami-active-tab-test` 启动独立 HTTPS 实例，使用六个临时 Shell 会话；不使用用户会话发送测试输入。
- 桌面 Chrome 实际渲染生产构建。1280、1920、2560、3440 CSS px 均验证侧栏关闭和打开：宽度分别为 0 / 320px，标签栏内容高 39px，选中线 4px，无横向或纵向文档溢出，当前项可见。
- 实际鼠标点按页面与会话标签，底线随当前项切换。按用户修订，选中文字使用 `--text-bright`：深色主题保持白色、浅色主题使用深色文字，蓝色仅用于底线。前后截图仅覆盖旧选中样式，以保持相同的会话、尺寸和内容。
- Android Redmi Note 8 真机，LAN HTTPS、硬刷新、CDP 坐标命中点按：首页、项目、工具、设置依次可达，`data-size=compact`、`data-pointer=coarse`，均无横向溢出；底部导航每项内容高 60px。打开临时会话时显示其名称和所属项目，键盘保持收起；点左上角收起后回到项目页。手机继续使用原有专用导航，未新增桌面标签栏。
- 键盘 Tab 可聚焦页面标签，`:focus-visible` 为真且焦点轮廓可见。通过右键菜单固定当前页面后，标签宽 44px、底线仍为 4px，底线不接收指针事件。
- `proposal.html` 已在 Chrome 实际打开，点选后前后两组同步切换，CSS 相对资源可读，无文档横向溢出。

## 自动检查

- `npm run typecheck`、`npm run i18n:check`、`npm run hover:check`：通过。
- `npx vitest run`：261 个测试文件、1915 个测试通过。
- `npm run build`：通过；已有大体积 chunk 提示保留。
- `scripts/dev/quality/check.sh quick`、`scripts/dev/quality/check.sh full`：通过，按改动范围跳过 Python 检查与 Go 测试。
- `git diff --check`：通过。新增前端行无 emoji 或文字图标；未新增产品文案。
- Impeccable 检测已运行；4 项既有提示来自未修改区域的边框及项目规定的字体，不扩展本次范围。

## 证据

本次 PNG 保留在 `/tmp/active-tab-session-before.png`、`/tmp/active-tab-session-after.png`、
`/tmp/active-tab-desktop-light.png`、`/tmp/active-tab-phone-after.png`、
`/tmp/active-tab-phone-session.png`、`/tmp/active-tab-proposal.png`。
截图通过 `scripts/dev/pr-shot.sh` 上传 `pr-shots` 分支，PR 正文提供 raw 链接，不提交到主分支。
浏览器测量原始数据保留在 `/tmp/active-tab-desktop-results.json` 和 `/tmp/active-tab-phone-results.json`。

## 白色标题修订

按用户确认保留底部蓝线，将选中文字从 `--accent` 改为 `--text-bright`。
重新验证四档桌面侧栏开合、深浅主题、页面与会话切换，以及 Android 四个主导航入口。
深色文字实际为 `rgb(230, 237, 243)`，浅色为 `rgb(31, 35, 40)`，底线仍为 4px。
1915 项测试与 full 质量门禁重新执行；quick 由本次提交钩子执行。
修订后的截图及测量数据使用 `/tmp/active-tab-white-` 前缀保留，PR 正文展示修订后截图。
