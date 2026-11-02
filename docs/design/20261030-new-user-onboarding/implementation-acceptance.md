# 初版实现验收（PR #550 前）

最新基线及验证结果见 [PR #550 适配验收](pr550-rebase-acceptance.md)。

2026-10-31。本记录针对最初接入产品后的实现；[原型验收](acceptance.md)保留为历史证据。

## 自动检查

| 检查 | 结果 |
| --- | --- |
| `scripts/dev/quality/check.sh full` | 通过；Go 全量测试，Python 依赖同步 / ruff / 测试，前端类型 / 翻译 / hover / 构建，敏感信息和文件策略检查 |
| Python runtime | 2469 passed，47 skipped；新增验证测试覆盖相同路由复用、证明权限、配置和凭据失效、空回复及失败撤销 |
| 前端最终检查 | typecheck、i18n:check、hover:check、build 均通过；152 个测试文件，1115 项测试通过 |
| 最终 Go 检查 | `go test ./...` 通过；覆盖独立临时目录、输出验证、程序改变、证明权限、认证文件改变、Claude 启动计数和自定义认证目录 |
| 差异检查 | `git diff --check` 通过；新增引导组件无 emoji / 文字符号图标 |

全量质量门完成后仅修改过前端细节和 Go 验证摘要；分别重新运行前端全套与 Go 全套。Python 实现未在全量质量门后改变。

## 真实产品链路

通过 `scripts/dev/isolated-roami.sh` 建立两个专用 HTTPS 实例，分别覆盖已有项目节点和全新空节点。运行真实构建产物、Go API、Python runtime 和 Go 模型网关。主模型验证使用本地 SSE 响应夹具，执行器验证使用测试可执行文件；任务提交阶段实际启动了本机 Codex，见下方更正。未替用户安装 CLI 或进行账号授权。

- 已有项目节点登录不自动打断工作；显式打开设置中的引导可重入。
- 全新节点登录留在首页，四项起步清单可见；修复了旧登录流程无条件跳项目页的问题。
- 在真实模型表单保存连接和主 / 后台模型，经过网关完成调用，读取 `verified=true`。
- Codex 通过显式运行验证后才进入可选执行器；已安装不自动等于可用。
- 创建普通新目录 `/tmp/roami-onboarding-project-00ac`，项目创建成功，没有自动初始化 Git。
- 任务示例作为普通文字填入，不加文件引用标记；通过现有提交按钮创建会话并发送任务。实际偏好记录完成、项目和会话，随后进入工作区。
- 完成表示已提交，未据此宣称测试智能体完成业务任务。
- 配置草稿修改、保存后验证失败、读取失败、偏好晚加载、节点切换和陈旧响应由组件测试覆盖。

## 布局和真机

- 真实产品以同源 iframe 运行，在 320 / 390 / 820 / 1100 / 1280 / 1600 / 1920 宽度检查七个模块详情和四个步骤，中文深色、英文浅色各 77 个组合，共 154 个组合；没有文档 / 内容横向溢出、文档滚动或底部动作被挤出视口。记录：[中文深色断言](/api/file/tmp/roami-onboarding-responsive-all.json)、[英文浅色断言](/api/file/tmp/roami-onboarding-responsive-light-en.json)。
- 实际产品验证中文深色和英文浅色。主题和语言通过隔离节点偏好及其浏览器镜像设置，未用临时 CSS 替换产品令牌。
- Redmi Note 8、Chrome 154、1080×2340、约 392 CSS px、coarse 指针，在 LAN HTTPS 下验收。使用独立测试域名，避免覆盖正常服务的登录 cookie。
- ADB 真实点按：首页进入模块列表、能力详情、顶栏返回、继续设置。能力七类全部出现；只有一个顶栏，底栏保持首页 / 项目 / 工具 / 设置。
- ADB 真实滑动使介绍内容 `scrollTop` 从 0 增至约 355；文档不滚动，底部动作仍可达。
- 真实点按 Base URL，软键盘打开；输入框和保存区可见，辅助页脚及底栏让位。实际输入测试地址后关闭键盘，进入模块介绍再继续设置，地址草稿保留。刷新前出现浏览器未保存提醒。
- 手机通过真实表单获取模型、选择模型、验证并保存；Codex 验证后继续，新建普通目录并提交首个任务。服务端偏好记录 `completed=true`、项目和实际会话。Enter 仅插入换行，真实点击提交按钮才创建会话。
- 发现任务输入区的提交按钮会在键盘弹出后落到可视区外，补充基于 `useLayout().keyboard` 的滚动定位；最终在键盘打开时完成真实按钮提交，并验证普通键盘输入不触发任务。
- 手机 `roami chrome --cdp` 返回 `CHROME_BROWSER_IDENTITY_UNAVAILABLE`，因此用本任务独立 CDP 转发读取断言；真实点击、滑动和输入仍走 `roami adb`。

## 截图

截图为实际产品；不提交一次性图片到主干。若后续发 PR，按仓库规则上传 `pr-shots`。

- [空节点首页 · 桌面](/api/file/tmp/roami-onboarding-implemented-home-desktop.png)
- [空节点首页 · Android](/api/file/tmp/roami-onboarding-implemented-home-phone.png)
- [主智能体 · 英文浅色桌面](/api/file/tmp/roami-onboarding-implemented-model-desktop.png)
- [主智能体 · Android](/api/file/tmp/roami-onboarding-implemented-model-phone.png)
- [软键盘 · Android](/api/file/tmp/roami-onboarding-implemented-keyboard-phone.png)
- [模块介绍 · 桌面](/api/file/tmp/roami-onboarding-implemented-tour-desktop.png)
- [能力介绍 · 英文浅色桌面](/api/file/tmp/roami-onboarding-implemented-tour-light-desktop.png)
- [能力介绍 · Android](/api/file/tmp/roami-onboarding-implemented-tour-phone.png)
- [任务输入与键盘 · Android](/api/file/tmp/roami-onboarding-implemented-task-keyboard-phone.png)
- [实际会话 · Android](/api/file/tmp/roami-onboarding-implemented-session-phone.png)
- [已提交回执 · Android](/api/file/tmp/roami-onboarding-implemented-submitted-phone.png)
- [首个任务 · 桌面](/api/file/tmp/roami-onboarding-implemented-task-desktop.png)

## 清理

验收结束后关闭本任务创建的浏览器测试页，移除任务专用 ADB 转发，停止两套隔离实例；tmux 仅通过各自的 `isolated-roami.sh <目录> --stop` 清理。截图和日志保留在 `/tmp` 供 review。

## 隔离偏差与更正

发现测试服务的 PATH 指向 Codex 夹具，但私有 tmux 的登录 shell 仍解析到本机 Codex。三次首个任务验收实际使用了已有 Codex 账号：桌面一次、手机两次。此前“未消耗模型额度”的进度说明不准确，已更正；主模型和执行器验证本身仍使用本地夹具。

仅核对 `session_meta.cwd` 为本任务两个临时项目目录的三段本机 Codex 对话，记录总用量为 414745 tokens，其中输入 412261（缓存输入 339328）、输出 2484；这是 CLI 日志统计，不代表账单金额。没有查询其他目录的对话正文。后续同类测试必须在测试节点的启动命令中指定夹具的绝对路径，不能只修改服务进程 PATH。

已通过各自的隔离入口停止两个测试 tmux 服务及其会话，并停止匹配这两个 `ROAMI_HOME` 的 Web / runtime / gateway / provider 进程；复查无残留任务进程。桌面测试页、手机测试页和专用 ADB 转发均已关闭。两个临时项目目录仍为空；截图和日志保留以便核对。
