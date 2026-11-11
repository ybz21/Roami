# 导航顶栏全屏入口

## 产品设计与用户故事

用户在展开的桌面导航中，可直接从 Roami 品牌行进入或退出浏览器全屏。
入口位于收起侧栏按钮左侧，沿用导航图标按钮的样式、焦点与触控命中区。
轨态不增加横向按钮；手机继续使用设置中的全屏入口。不支持 Fullscreen API 时隐藏入口。

## 技术设计

- `AppShell.tsx` 将现有 `useBrowserEnvironment` 的能力、状态和切换动作传给 `Navigation`。
- `Navigation.tsx` 复用 `FullscreenIcon`、`ExitFullscreenIcon` 和已有中英文翻译；提供 `aria-label` 与 `aria-pressed`。
- `useBrowserEnvironment.ts` 挂载时读取当前全屏状态，并沿用标准及 WebKit 全屏变化事件同步后续状态。
- 不新增样式、偏好、依赖或请求。

## 验收记录

2026-11-11，使用独立 tmux 测试实例 `/tmp/roami-fullscreen-check`，HTTPS 端口 18563。

- 前端 typecheck、i18n:check、hover:check、生产 build 通过；226 个测试文件、1625 项测试通过。
- `scripts/dev/quality/check.sh quick`、`scripts/dev/quality/check.sh full` 通过。未修改 Python 或 Go 代码。
- 独立桌面 Chromium：1280、1920、2560、3440 CSS px，侧栏展开及收起均无文档横向溢出。
- 实际点击品牌行按钮进入全屏、点击退出按钮恢复，`aria-pressed` 和图标同步；外部 `document.exitFullscreen()` 后入口恢复。
- 中文与英文入口分别显示“全屏 / 退出全屏”和“Fullscreen / Exit fullscreen”，均可切换。
- 无头 Chromium 不执行浏览器级 Esc 退出，因此用外部退出事件验证同一状态同步路径；未将模拟键盘结果当作真实 Esc 验收。
- Redmi Note 8 / Android Chrome，经 LAN HTTPS 加载当前生产包，ADB 点按原有设置入口进入并退出全屏，确认 `document.fullscreenElement` 随之变化；手机无横向溢出，顶栏和底栏存在。

截图与原始验收数据保留在本机，不提交图片：

- `/tmp/roami-fullscreen-after.png`：桌面界面。
- `/tmp/roami-fullscreen-button.png`：新增入口。
- `/tmp/roami-fullscreen-phone-active.png`：Android 真机。
- `/tmp/roami-fullscreen-desktop-results.json`：桌面布局与交互结果。

本机 Roami Chrome CLI 的共享标签预算已满，独立 Chrome 启动也遇到浏览器进程故障；最终使用 Playwright 启动独立 Chromium 验收。手机 CLI 返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`，改用原生 CDP 读取状态及 ADB 真实触控。
