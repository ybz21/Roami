# 智能体 Logo 下拉导航验收

2026-11-15，第三版。范围为设计资料与独立原型，未修改产品功能。

## 已核对

- 顶部入口直接复用项目 `AgentLogo`，演示中“海空双模式”为 Claude、“登录流程”为 Codex，均为官方路径与品牌色。
- 名称 / Logo 和箭头为独立按钮；主入口始终回对话，箭头不触发资源切换。左侧没有组内资源栏，顶部也没有展开的文件标签列表。
- 菜单首项为对话，其后是已打开文件；文件标题显示当前文件，菜单用选中底色、字重和勾选图标标出当前项。
- 菜单通过 portal 展示，未被导航裁切；开关不影响主工作区尺寸。

## Chrome 实际交互

以下断言通过，页面脚本错误为 0：

- 点 Logo / 名称直接进入指定对话；点另一会话的箭头只查看菜单，不先切走当前文件。
- 点文件进入指定文件并收起菜单；文件和分组对话草稿保留，两个会话草稿互不串用。
- 对话与文件的当前项标记正确；无文件的会话只出现“对话”。
- Home、下方向键和 Escape 正常；Escape 将焦点还给对应箭头。
- 外点关闭不改变文件或草稿；浏览器返回恢复实际访问位置。
- 属性栏在 1280 / 1920 / 2560 / 3440 下开合正常；收起时主内容宽度等于整个工作区，展开时仅减去 260 CSS px。
- 深浅主题均已截图。

## 尺寸与弹层边界

视口高度 900 CSS px，检查宽度为 1280 / 1920 / 2560 / 3440 / 320 / 390 / 820 / 1100。

所有宽度均无文档横向溢出，菜单左右边界与底边均在视口内，侧栏均不存在。窄端菜单宽度自动收缩，320 CSS px 下不撑大文档。桌面交付截图为 1280 × 800。

## Android 真机

Redmi Note 8，设备 `216d6a43`，Chrome 经 LAN 打开并硬刷新原型。实际为 `compact` / `coarse`，宽度 392 CSS px，无文档横向溢出。

- ADB 点击 `(992,450)` 的下拉箭头，文件保持显示，菜单打开，`交互方案.md` 标为当前项。
- 点击 `(400,960)` 选择菜单“验收清单.md”，实际打开该文件，菜单关闭。
- 点击 `(300,450)` 的智能体 Logo / 名称区，实际回到对话，输入区出现。
- 再点箭头，菜单“对话”标为当前项，文件项不再误标。
- 菜单项高度 44 CSS px；名称按钮高度 44；箭头视觉 32，经粗指针伪元素扩至 44。
- 截图覆盖关闭菜单的文件页、展开菜单的文件页、对话页和对话菜单。

手机读取 / 截图使用目标页原生 CDP WebSocket，触摸仍通过 `roami adb shell input tap` 验证；没有修改用户业务页面或回放未知业务动作。

## 检查与产物

- 原型 esbuild 构建通过；图标和尺寸档位复用 `icons.tsx` 与 `useLayout()`。
- Impeccable detector 输出 `[]`；`git diff --check` 通过。
- `scripts/dev/quality/check.sh quick` 通过，包含既有产品 typecheck、i18n 与 hover 检查。
- HTML / CSS / JS 相对资源已核对；前两版快照保留在 `revisions/v1/`、`revisions/v2/`。
- 本次仅修改设计目录和设计索引，不修改 `frontend/**`、Go、Python 或产品语言包。设计资料中文属于开发者原型；产品落地须接现有中英 i18n。

本机证据：`/tmp/session-agent-dropdown-results.json`、`/tmp/session-agent-dropdown-quality.log`、`/tmp/session-agent-dropdown-open.png`、`/tmp/session-agent-dropdown-closed.png`、`/tmp/session-agent-dropdown-light.png`、`/tmp/session-agent-dropdown-phone-open.png`、`/tmp/session-agent-dropdown-phone-chat.png`、`/tmp/session-agent-dropdown-phone-chat-menu.png`。截图经 `pr-shot.sh` 进入 `pr-shots`，不提交到主分支。

## 产品实现后再验收

真实文件保存 / 关闭、长列表和同名文件、多会话共享工作区、来源失效、跨节点、真实滚动恢复、服务端状态迁移、完整中英显示、软键盘及安全区，仍须在产品实现后验证。原型没有真实发送、保存、关闭或终端能力。
