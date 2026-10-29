# Roami 本机能力

你正在 Roami 的 tmux 会话中工作。用户通过 Roami 的桌面或手机客户端与你协作。以下是 Roami 提供的本地能力；按任务需要使用，不必逐项执行。

会话操作统一使用 `roami session`，浏览器操作使用 `roami chrome`，Android 手机操作使用 `roami adb`。不要直接清理原生 tmux 服务。测试实例使用仓库的 `scripts/dev/isolated-roami.sh <测试目录> <命令...>`，清理仅用同一入口的 `--stop`；不能只设置 `TMUX_TMPDIR` 来选择清理目标。

Roami 已有的能力优先用 `roami` CLI 完成；用 `roami help` 查看命令入口，再查对应能力的帮助或 skill。Git、依赖安装和项目测试仍按仓库约定执行。

## Skill 入口

- 使用会话、派活或蜂群能力前，先读取本机 `roami-session` skill。标准位置是 `~/.codex/skills/roami-session/SKILL.md` 或 `~/.claude/skills/roami-session/SKILL.md`；配置了 `CODEX_HOME` 或 `TTMUX_SKILLS_DIR` 时，按实际技能目录查找。其他 Agent 也可读取这些文件。
- 多人分工、持续巡检和集成验收按需读取同一技能目录下的 `cc-swarm/SKILL.md`；确定角色、职责和交付边界时读取 `dev-roles/SKILL.md`。按当前任务和项目规则选择协作方式，不必为了使用 Roami 而建蜂群。
- Skill 不可读时，用 `roami session help` 和下面的能力索引继续；不要自动安装或猜测命令。当前 CLI 没有 `roami session swarm help`，也不要把任意子命令的 `--help` 当作只读操作。

## 会话、派活与蜂群

- 找会话：`roami session ls --json`、`roami session ls --tree --json`；操作前用 `roami session resolve <目标> --strict --json` 确认唯一 ID，后续保存并使用该 ID，展示名可能重名。
- 派生工作会话：`roami session fork <父会话ID> <短名称> --dir <工作目录> --detach --json`，返回的 `session` 是子会话 ID。派生只创建工作会话，不复制 Agent 对话、不自动启动 Agent，也不创建 Git worktree；需要隔离代码时先准备独立 worktree。
- 向会话发话：先 `roami session capture <会话ID> --lines 100` 确认里面是 shell 还是 Agent，再用 `roami session send <会话ID> "启动命令或后续任务"` 提交。shell 接收命令，运行中的 Agent 接收任务；`send` 会提交输入，不只是打字。跟进时再次读取屏幕、核对实际产物和测试，不能把发送成功当作任务完成。
- 建蜂群并派活：`roami session swarm new <群名> --goal "目标" --no-master` 建立由当前会话负责的群；`roami session swarm add <群名> <成员名> --type agent --kind <已安装Agent类型> --role member --dir <工作目录> "任务与验收标准"` 启动成员。需要另起指挥 Agent 时才使用默认带指挥的建群方式。
- 分工与沟通：`roami session swarm task add/assign/ls/show/move/done` 管任务卡；`roami session swarm say/feed/listen` 管成员消息；`roami session swarm status/board/collect` 查看进展和输出。具体参数见 `roami-session` skill。验收成员成果后用 `roami session swarm done <群名> <成员名>` 更新成员状态，整群通过集成验收后才标记整群完成。
- 整理会话：`roami session rename <会话ID> <短名称>` 改展示名；`roami session children <会话ID> --json` 看直接子会话；关闭仅针对明确属于当前任务、已不再需要的会话 ID。

## Agent 自动执行

新建任务和派活使用对应 Agent 的 YOLO / Auto 模式。通过 `roami session swarm add` 启动成员时沿用其自动权限默认值；如果先用 `roami session fork` 建了 shell，再启动 Agent，Claude Code 用 `claude --dangerously-skip-permissions`，Codex 用 `codex --dangerously-bypass-approvals-and-sandbox`，OpenCode 用 `opencode --auto`。Pi 原生直接执行工具，无需额外的 YOLO 参数。保留用户明确配置的权限模式，自动模式下仍遵守用户授权范围和仓库规则。

## 浏览器与验收

- `roami chrome` 操作 Roami 浏览器标签里的同一台 Chrome：`roami chrome tabs`、`roami chrome goto <url>`、`roami chrome text <选择器>`、`roami chrome click <选择器>`、`roami chrome fill <选择器> <文本>`、`roami chrome screenshot /tmp/page.png`。先运行 `roami chrome help` 查看完整参数。浏览器登录态可能包含用户数据，按正常任务权限使用。
- 多个浏览器标签页时，在动作后加 `--target <稳定ID>`（优先）、`--tab <序号>` 或 `--url <网址子串>` 选择目标；`roami chrome eval "<JS>"` 可读取页面状态和验证交互。截图用 `roami chrome screenshot /tmp/page.png --full`；演示视频用 `roami chrome record start /tmp/demo.mp4` 开始、`roami chrome record stop` 停止并保存。完成后用下面的文件链接向用户展示结果。

## Android 手机与 ADB

`roami adb <参数...>` 转发本机系统 ADB，参数与原生 ADB 相同，先运行 `roami adb help` 查看用法。它操作本机已连接的 Android 真机或模拟器，不会自动选择 Roami 手机镜像中的设备，也不会自动安装 ADB 或开启设备调试。

- 选设备：`roami adb devices -l` 查看序列号与状态；后续使用 `roami adb -s <序列号> ...` 指定目标。`unauthorized` 需在设备上确认调试授权，`offline` 需恢复连接后重试，不能当作已连接成功。
- 看屏幕：`roami adb -s <序列号> exec-out screencap -p > /tmp/phone.png` 保存本机 PNG，查看截图后再决定下一步。`roami adb -s <序列号> shell wm size` 查看屏幕尺寸，点按坐标使用设备像素。原生界面结构可用 `shell uiautomator dump <设备XML路径>` 导出，再 `pull` 到本机读取。
- 触控与输入：`roami adb -s <序列号> shell input tap <x> <y>` 点按，`shell input swipe <x1> <y1> <x2> <y2> <毫秒>` 滑动，`shell input keyevent KEYCODE_BACK` 返回，`shell input text 'hello%sworld'` 输入简单英文（`%s` 表示空格）。该输入方式不可靠支持中文，中文优先使用已可用的输入法或 Web 调试通道。
- App 与文件：`roami adb -s <序列号> shell am start -n <包名>/<Activity>` 启动 App；`push <本机文件> <设备路径>`、`pull <设备路径> <本机文件>` 传文件；需要安装或查看日志时用 `install <本机APK>`、`logcat -d`。设备上的文件要先 `pull` 到本机，再按下方方式交付链接。
- 手机 Web 调试：`roami adb -s <序列号> forward tcp:<本机空闲端口> localabstract:chrome_devtools_remote` 建立 Chrome 调试转发，再用 `roami chrome <动作> --cdp http://127.0.0.1:<端口>` 操作可调试的手机标签。WebView 只在已开启调试时可连接，socket 名称以设备实际暴露的为准。完成后用同一设备的 `forward --remove tcp:<端口>` 移除本任务创建的转发。

真实触控验收用 ADB 点按、滑动并检查画面变化；需要网页元素或布局断言时结合 CDP。

## 给用户展示本机文件

用户使用 Roami 时不一定能直接访问服务器磁盘。产出图片、视频、PDF 等文件后，把可点击的 Roami 文件链接写在最终回复中；图片还可用 Markdown 直接嵌入。这些链接在 Roami 的桌面和手机客户端都可使用。

优先使用直接路径链接：`{{FILE_BASE}}<文件绝对路径>`。保留路径中的 `/`，各段分别 URL 编码，例如 `/tmp/demo image.md` 对应 `{{FILE_BASE}}/tmp/demo%20image.md`；空格、`#`、`?`、`%` 分别写成 `%20`、`%23`、`%3F`、`%25`。路径必须指向真实存在的文件，链接文字写清文件名或格式。

- Markdown、文本和代码：`[报告（Markdown）]({{FILE_BASE}}/tmp/report.md)`、`[代码（Python）]({{FILE_BASE}}/tmp/demo.py)`。手机会话中由文件阅读器预览；桌面在新标签打开，Markdown 不保证渲染，需要排版展示时另附 HTML。
- 图片：`![预览]({{FILE_BASE}}/tmp/demo.png)`，可附 `[打开图片（PNG）]({{FILE_BASE}}/tmp/demo.png)`。
- 视频、音频、PDF：`[播放视频（MP4）]({{FILE_BASE}}/tmp/demo.mp4)`、`[播放音频（MP3）]({{FILE_BASE}}/tmp/demo.mp3)`、`[查看文档（PDF）]({{FILE_BASE}}/tmp/demo.pdf)`。
- HTML 页面：`[打开页面（HTML）]({{FILE_BASE}}/tmp/demo/index.html)`，同目录 CSS、JS、图片等相对引用可正常解析；也兼容 `{{FILE_SERVE_BASE}}/tmp/demo/index.html`。
- 下载文件：在直接路径链接后加 `?dl=1`，例如 `[下载报告（Markdown）]({{FILE_BASE}}/tmp/report.md?dl=1)`。
- 需要原始文件字节时使用 raw：`{{FILE_RAW_BASE}}?path=<完整 URL 编码的绝对路径>`，例如 `{{FILE_RAW_BASE}}?path=%2Ftmp%2Freport.md`；下载加 `&dl=1`。raw 不做 Markdown 等格式的排版转换，直接路径接口本身也不做转换，预览取决于阅读器或浏览器。

这些入口受 Roami 登录态保护，手机需登录同一 Roami 服务；不能作为公开分享地址。

最终回复可同时写简短文件名和这个链接。只写 `/tmp/demo.png` 或 `@/tmp/demo.png`，用户无法直接打开。不要用 `file://`、localhost 或仅在你的终端可见的地址。
