# 产品实现与验收

2026-11-16。本记录对应真实产品，历史原型证据保留在 [acceptance.md](acceptance.md)。

## 已实现

- 顶部使用真实智能体 Logo、会话名和独立的资源箭头。点击名称始终激活会话，清空活动文件选择；侧栏会话入口遵循同一规则。
- 组内文件收进下拉菜单，不再铺成独立顶部标签，也不增加左侧资源树。无可见来源会话的文件保留独立入口，避免关闭会话后丢失文件入口。
- 菜单先显示对话，再列已打开文件；当前项、未保存标记和关闭动作均可用。同名文件展示完整路径。
- 没有打开文件时不渲染箭头。打开第一个文件后出现，关闭最后一个文件后移除并把菜单焦点还给会话名称。
- 文件标题前可返回来源会话。失效来源退回同工作区有效会话；关闭当前文件优先选择同组相邻文件，最后一个文件关闭后返回当前同组会话。
- 手机保持同一个智能体顶栏，另有会话切换入口；“更多 → 文件”打开全屏文件浏览器，选中文件返回工作区并启用资源菜单。
- 草稿保留与未保存关闭确认继续由既有文件资源管理；菜单不跳过确认。中英标签与可访问名称接入现有 i18n。

## 模块与状态

| 模块 | 职责 |
| --- | --- |
| `SessionResourceMenu.tsx` / `session-resources.css` | antd 菜单、当前资源、键盘与焦点、触控命中区；没有文件时不生成入口 |
| `TerminalPane.tsx` | 派生各会话的工作区文件，组合桌面及手机顶栏；复用文件关闭保护与文件浏览器 |
| `useTaskWorkspace.ts` | 原子激活会话 / 文件、校验归属、关闭同组文件及来源返回 |
| `WorkspaceTerminals.tsx` / `AppShell.tsx` | 将侧栏、手机和顶部入口接到同一个导航动作 |
| `FilePathBar.tsx` | 标题前返回与文件关闭；继续复用 `BackButton` |

分组复用 `TaskKey` / `FileTab.task`，同一工作区的多个会话共享一份文件列表；不创建组实体、服务端接口或轮询。文件来源用统一 `view-state` 仓库的节点 / workspace / files / file 作用域保存稳定会话 ID。菜单开合、DOM 引用与焦点保持组件所有权。原有编辑器草稿与 `/workspace` 打开资源继续由原有状态所有者管理。

## 自动验证

- `npm run typecheck`、`npm run i18n:check`、`npm run hover:check`、`npm run build` 通过。
- `npx vitest run`：254 个文件、1833 项测试全部通过。新增菜单测试覆盖无文件入口、当前项、关闭最后一项、同名路径、Escape 焦点；工作区测试覆盖同组共享、多组切换、来源返回、关闭相邻文件、手机保留孤立文件。
- `scripts/dev/quality/check.sh full` 与提交前 quick 通过。仅前端和设计文档变化，按质量入口判断跳过无关 Python / Go 运行测试。
- `git diff --check` 通过；Impeccable 对新增组件 / 样式的源码模式扫描无报告项，浏览器视觉与触控另行实测。

构建前的同提交基线和改后均实际运行生产构建；本次不据构建耗时声称 CPU 或内存收益。

## 真实产品交互

独立实例经 `scripts/dev/isolated-roami.sh /tmp/session-nav-product-test ...` 运行，使用 HTTPS、私有 tmux server 和一次性仓库。两条会话是真实 PTY；Claude / Codex 标志由空闲进程夹具触发，用于验证真实类型检测和导航，不进行模型调用。文件读取、Monaco 编辑、关闭确认及工作区 API 均走真实产品。浏览器使用独立 context，手机只操作本任务测试页。

桌面 Chrome 实测：

- 名称直达会话、菜单选择文件、Escape 收起并恢复箭头焦点；文件不再显示为顶部独立标签。
- Monaco 中实际输入未保存文本，回对话再打开文件，草稿保留；取消关闭不丢内容；明确放弃后才关闭。
- 关闭最后文件时箭头消失，当前入口与键盘焦点回到会话。
- 1280 / 1920 / 2560 / 3440 CSS px 下菜单不越界，文档无横向或纵向溢出。属性栏开合前后工作区宽度分别为 1224/904、1864/1544、2504/2184、3384/3064，收起后完全恢复；内容高度均为 792 CSS px。
- 深色中文和浅色英文均实际打开；页面脚本错误为 0。

Redmi Note 8 真机，经 HTTPS 测试页硬刷新，实际为 compact / coarse、DPR 2.75：

- ADB 真点按“更多 → 文件 → 交互方案.md”，从零文件状态打开第一个文件；文件浏览器关闭，导航箭头出现。
- 点 Markdown 中的相对链接实际打开验收清单，并加入同组菜单。
- 点击名称回对话、菜单“对话”返回、选择另一文件、标题返回均验证通过。
- 箭头视觉 24 CSS px，实际触控区至少 44；名称区高 44。`elementFromPoint` 横扫箭头与邻钮之间的缝隙均命中按钮；实际点原缝隙位置打开菜单。
- 菜单中依次关闭两个文件，最后一个关闭后菜单与箭头消失，名称区由约 192.7 扩至 228.7 CSS px，没有空占位。
- 菜单项触控高度超过 44，文件工作区和顶栏不被底栏遮挡，无文档横向溢出。
- 26 文件长菜单在真实手机上经 CDP 合成触摸滑动，菜单 `scrollTop` 从 0 增至约 298，视口高度约 618；文档高度保持 766，没有带动外壳滚动。验证后已恢复两文件夹具。

本次验证导航、文件资源与编辑保护，不宣称验证了真实智能体推理或模型发送。

## 证据

本机保留：

- `/tmp/session-nav-product-browser-results.json`、`/tmp/session-nav-product-layout-results.json`：桌面交互、四档布局与主题 / 语言结果。
- `/tmp/session-nav-final-all-tests.log`、`/tmp/session-nav-full-quality.log`：测试和质量入口输出。
- `/tmp/session-nav-phone-final-hits.log`、`/tmp/session-nav-phone-close-last.log`：真机命中与关闭最后文件后的布局。
- `/tmp/session-nav-product-before-desktop.png`、`/tmp/session-nav-product-after-desktop.png`：真实产品桌面前后。
- `/tmp/session-nav-product-before-phone.png`、`/tmp/session-nav-product-after-phone-menu.png`、`/tmp/session-nav-product-phone-no-files.png`：手机前后及零文件状态。
- `/tmp/session-nav-product-light-english.png`、`/tmp/session-nav-product-dirty.png`：英文浅色及未保存状态。

截图通过 `pr-shot.sh` 上传至 PR 932 的 `pr-shots`，不进入主分支。产物保留在本机；测试实例与私有 tmux server 经同一个隔离入口停止。
