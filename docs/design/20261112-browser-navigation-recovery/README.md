# 浏览器导航等待与卡死检测

## 产品设计

用户打开 GitHub Trending 时，页面保持空白，镜像显示“此标签页已停止响应”。现场标签最终落入 Chrome 的 `ERR_CONNECTION_CLOSED` 错误页；独立浏览器的直连与代理对照均成功，不能据此认定代理缺失是故障根因。

已复现的产品缺陷：网站等待响应期间，新文档的 JavaScript 上下文尚未就绪，镜像的同步 `Runtime.evaluate` 探测会超时，导致推流尚未启动就被判为卡死。前端的首帧超时又会重复断开慢导航。恢复入口新建标签时，同步等待 `Page.navigate` 还会丢失已创建目标的成功回执。

保持现有浏览器布局、标签分组与恢复按钮。导航等待期间维持连接；超过 30 秒显示“网页加载超时，请检查网络后重试”，保留控制和后续自动恢复。真正无响应的渲染器继续使用原有故障提示。

## 用户故事

- 网站响应超过 15 秒时，保留正在打开的标签，不因镜像重连反复中断。
- 网站加载超时后，能重新打开此页；网站稍后恢复时，镜像继续显示画面。
- 页面执行卡死时，仍能检测故障；子框架导航不能掩盖主页面卡死。
- 多个标签同时等待网络时，不以 JavaScript 暂未返回为由重启整台 Chrome。

## 技术设计

- `backend/browser/tabs.go`：直接把完整 URL 交给 `/json/new`，创建目标后登记分组并返回 ID，不再为新目标同步等待远端导航。
- `backend/browser/screencast.go`：先启动镜像，异步检测渲染器；仅跟踪目标主框架的 `Page.frameStartedNavigating`、`Page.frameNavigated`、`Page.frameStoppedLoading`。导航结束后废弃旧上下文探针，重新检测；30 秒导航超时只通知一次，不关闭连接。
- `backend/browser/lifecycle.go`：后台全局恢复探测识别主框架进行中的导航，避免把所有标签等待网络误判为整机失效。
- `frontend/src/components/mirror/browser-stream.ts`：收到导航状态时暂停首帧计时，导航结束后恢复计时；传输静默检测继续工作。
- `BrowserView.tsx` 与中英文语言包：区分加载超时提示，复用普通浏览器的重新打开按钮；固定任务目标不自动替换。

## 验收

回归用例覆盖首帧不依赖 JavaScript、慢导航正常结束、超时后继续出帧、旧上下文探针失效、子框架不能遮蔽主框架卡死、后台恢复识别导航、新标签立即返回完整 URL 与分组。前端覆盖导航期间心跳、结束后的首帧超时以及传输静默重连。

2026-11-12 验收：

- `go test -race ./backend/browser -count=1` 通过；浏览器与自动化模块测试通过。
- 前端 typecheck、i18n、hover、全部 1708 项 Vitest 测试、生产构建通过。
- `scripts/dev/quality/check.sh quick` 通过；未修改 Python，Python runtime/skill 检查按范围跳过。
- 独立 profile/CDP 的真实 Chrome：本地站点延迟 22 秒返回，创建标签回执约 29ms；等待期间未显示渲染器卡死，返回后显示 `Navigation recovered`。
- 永不返回的页面：30 秒后显示加载超时与重新打开按钮，连接继续响应心跳；恢复导航后重新出帧。
- BrowserView 隔离验收入口覆盖 1280、1920、2560、3440 CSS px，镜像舞台跟随容器、文档无横向溢出。本次未修改页面壳或可选工作区面板。
- Redmi Note 8 真机经 LAN 打开相同源组件，`compact/coarse`、392 CSS px、无横向溢出。ADB 真实点按恢复按钮：新目标立即出现，旧目标随后关闭，标签总数回到原值；测试站点恢复后镜像图片为 1920×1080，超时提示消失。地址栏也经过真实点按与键盘输入；测试入口未注册其导航 API，最终恢复由测试端 CDP 导航触发，不能把该步骤计为导航 API 验收。
- 本次手机验收使用独立 BrowserView 入口，未改动或重新验收应用外壳的顶部/底部导航；未重启、关闭或导航用户原有 Chrome 标签。

一次性证据在 `/tmp/roami-chrome-recovery-20261112`：`debug-after.png`（桌面恢复画面）、`desktop-timeout.png`（桌面超时）、`phone-timeout.png`、`phone-recovered.png`、`quality-quick.log`、`frontend-tests-final.log`、`frontend-build-final.log`。不提交截图进主分支。

修复尚未部署到正在使用的 Roami 服务；现场 GitHub 网络连接失败本身不由本修复保证消除。
