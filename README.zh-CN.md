# Roami

[English](README.md) ｜ **简体中文**

> **把你的开发机变成一个随身 AI 编程工作站。**

**Roami** 让你**在任何地方、任何时间，用手机、平板或电脑连回自己的开发机**，
继续写代码、跑测试、看日志、调浏览器，并监督 Claude Code、Codex 等
AI coding agent 持续工作。

它解决的是一个很具体的问题：**复杂开发任务不应该被你的设备、网络和时间切碎。**
代码、终端、开发服务、浏览器和 Agent 都留在开发机上持续运行；你换设备、断线、
离开桌面后，回来仍然接着同一个现场继续。除非你主动关闭，开发机上的工作不会因为
本地命令行退出、浏览器关闭或笔记本合盖而消失。

**一眼看懂 Roami 的价值：**

- **一切围绕项目组织**：每个仓库就是一个作战台——任务、worktree、编队、活动都挂在它名下；
  工作台是跨项目的作战地图，哪里需要你一眼可见。
- **远程开发不断线**：手机查看进度，平板补充指令，电脑接手编码，工作现场始终在开发机上。
- **长任务持续跑**：测试、构建、迁移、日志和调试会话不因合盖、断网、换设备而中断。
- **AI Agent 可管理**：描述任务，Agent 就在独立 worktree 里开干；既能当对话读，也能看原始
  终端，随时从任何设备追加指令。
- **复杂任务可编排**：同一任务让两个 Agent 竞赛对比，或拆给一个蜂群——目标、依赖、
  看板和消息流俱全。
- **不止一台机器**：笔电、工作站、Jetson 可以挂在同一个控制台后面——在同一个窗口里切换，
  一个页面就能看出它们是不是都健康。

Roami 不是另一个云 IDE。它连接你的真实开发机，把项目、终端、浏览器、文件、任务和
AI Agent 放进一个可远程接管的工作空间里。你看到的是一个控制台，背后仍然是你
熟悉的开发环境和工具链。

![Roami —— 左边是工作台，右边是正在干活的 Claude Code](docs/screenshots/hero.zh.png)

<sub>一个窗口装下两件事：所有项目里哪些需要你，以及此刻正在干活的那个 Agent。</sub>

## 核心能力

- **项目是工作的单位**：会话、任务、worktree、编队都挂在所属仓库名下——打开一个
  项目，它的一切一屏可达。
- **合上盖子，活儿照跑**：终端、开发服务、测试、Agent 对话都留在开发机上，断网或
  关掉笔电都不会让现场消失。
- **换设备如同回到同一张桌子**：手机、平板、笔电打开 Web 控制台，直接落回你离开时的
  那个项目——零安装，没有原生 App 要更新。
- **描述任务，Agent 接活**：写下你要什么，Claude Code 或 Codex 就在独立 worktree、
  独立分支上开干——还能让两个 Agent 竞赛同一任务，择优采纳。
- **读 Agent，而不是读终端**：正在跑的 Claude Code / Codex 可以当成一场对话来读——消息、
  diff、折叠起来的工具调用；也可以随时切回原始终端，看你当下需要哪个。
- **编队把一个目标分给多双手**：API 交给一个成员、前端交给另一个、测试交给第三个——
  共享看板和消息流让他们同步，依赖关系自动解锁下一步。
- **调试浏览器和真手机也在开发机上**：登录态、截图、复现流程都原地保留，远程调 UI
  接着上次继续。
- **人和 Agent 共用一个工作现场**：人可以从 Web 控制台亲手接管，Agent 也能读状态、
  收输出、继续推进。

## 界面截图

**工作台只回答一个问题：哪些事需要我？** 等你处理的项目排在最前，每个都带着进行中的
任务、worktree 数量和蜂群；右边是跨仓库的最近活动。

![工作台：需要你的事、各项目任务、最近活动](docs/screenshots/workbench.zh.png)

**读 Agent，不用读终端。** 同一个 Claude Code / Codex 会话可以渲染成对话：消息、代码块、
diff、折叠成组的工具调用，底下一条状态栏给出模式、上下文占用和耗时——还有一个回话框。

![把 Claude Code 会话渲染成对话](docs/screenshots/chat.zh.png)

**也可以直接要原始终端，因为它本来就是一个真 tmux 会话。** TUI 保真，标签按机器各记各的，
文件抽屉和 Git 面板一键可达；在手机上还有按键条和语音输入。

![同一个会话的终端形态，含工具栏与手机按键条](docs/screenshots/terminal.zh.png)

**编队一屏看懂。** 每个成员的实时拓扑、共享协作墙（广场）、可拖拽流转的看板、
等待处理的收件箱——一个被拆给多个 Agent 的复杂目标，依然清清楚楚。

![蜂群仪表盘：拓扑、广场、看板](docs/screenshots/swarm.zh.png)

**多台机器，一个控制台。** 中心页用一行说清中心健不健康，列出每台机器的延迟、CPU、
内存和会话数，再给一条最近发生了什么——谁掉线了、谁回来了、断了多久。

![中心页：中心健康、机器列表、最近事件](docs/screenshots/hub.zh.png)

**设置终于能找得到东西。** 名称、说明、键名都能搜；分类按作用域分组——哪些跟着你走、
哪些属于这台机器、哪些是整个集群的。

![设置：搜索、分类树、一类一页](docs/screenshots/settings.zh.png)

**不离开控制台就能翻文件、改文件。** 文件夹和文件两栏可拖宽，悬浮即预览，
路径可以直接拖进终端或 Agent 输入框。

![文件工作区：文件夹栏、文件栏与预览](docs/screenshots/files.zh.png)

**在控制台里直接操控一台真浏览器。** 开发机上的 Chrome 被镜像进控制台——开标签、
导航、点击、输入都行。调试网页、保住登录态，或让 Agent 复现一整套流程，全在开发机上完成。

![浏览器镜像：控制台里操控一个真实 Chrome 标签](docs/screenshots/browser.zh.png)

**在控制台里直接操控一台真手机。** 通过 adb 镜像 Android 设备——实时画面、串流指标、
远程导航栏都在——用来复现移动端流程，或在终端旁边顺手看个 App。

![手机镜像：控制台里的一台真实 Android 设备](docs/screenshots/phone.zh.png)

## 移动办公：随时随地接着干

**整套工作现场，装进一部手机。** 用任意手机浏览器打开控制台——无需装 App——直接落回
同一批项目、任务和 Agent。底栏放着你真正会去的五个地方，会话坞让正在跑的 Agent
永远只差一次点击。

![手机上的 Roami：工作台与会话坞](docs/screenshots/mobile-office.zh.png)

**在手机上直接和 Agent 对话。** 打开一个会话就能当对话读——和桌面同一套卡片、diff
和状态栏——然后打字或说话追加指令，把活儿往前推，不用开电脑。

![在手机上和 Claude Code 对话](docs/screenshots/mobile-chat.zh.png)

## 为什么需要它

远程开发在小任务里很简单，但一旦任务变复杂，就会遇到很多断点：

- 开发服务要一直跑着
- 测试、日志、构建需要多个终端
- 浏览器状态对复现问题很重要
- Agent 需要独立上下文和后续指令
- 长任务要能在你离线后继续执行
- 你需要按项目快速知道哪些任务还在跑、哪些在等你
- 机器多于一台之后，你还得知道某个会话到底在哪台上

Roami 把开发机作为唯一真实工作现场。服务器负责保持工作持续运行，Web 控制台负责让
你从任何设备接入；需要自动化时，再通过脚本接口把会话、任务、日志和 Agent 编排接入流程。

## 典型使用方式

1. 在开发机上启动 Roami。
2. 从手机、平板或另一台电脑打开 Web 控制台。
3. 打开一个项目，进入已有任务或终端，继续之前的开发现场。
4. 描述新任务，让 Claude Code、Codex 或其他 Agent 在开发机的独立 worktree 里执行。
5. 离开浏览器或关闭本地命令行后，开发机上的终端、服务、日志和 Agent 仍继续运行。
6. 稍后从任意设备回来：工作台告诉你哪些项目在等你，项目页告诉你每个任务跑到哪了。

Roami 的重点不是「多一个终端工具」，而是让开发机变成一个持续在线的工作空间。你在
开发机上打开的终端、运行中的服务、调试浏览器、AI Agent 对话和任务状态，不会因为
本地设备关机、SSH 断开、浏览器关闭而主动消失。

## 安装与启动

完整安装包包含内嵌前端的 `roami`、独立 Python 和智能体生产依赖；目标机无需预装 Python、uv、Go 或 Node。浏览器自动化另需 Node 与 Chrome。
配置与数据都在 `~/.roami/`（`config.yaml` 首次运行自动生成）。

### 方式 A — 装成常驻服务（推荐给 24 小时常驻运行的机器）

一条命令安装完整环境并注册常驻服务（Linux 使用 systemd，macOS 使用 launchd）：

```bash
curl -fsSL https://raw.githubusercontent.com/ybz21/Roam/main/install.sh | bash
```

`install.sh` 把入口装到 `~/.local/bin`，完整环境保存在 `~/.local/share/roami/releases/`。它在目标机创建 venv，使用包内 wheel 离线安装依赖，并验证设置保存与重启恢复后再切换版本。重复执行同一条命令即可升级；任务正在执行时会保留旧版，提示稍后重试。

Linux 用 `systemctl --user {status|restart|stop} roami` 管理；macOS 使用 `~/Library/LaunchAgents/com.roami.console.plist`。Roami 自动守护智能体子进程，崩溃后退避重启；模型地址和密钥仍在网页填写。用 `roami agent status` 查看运行状态，`roami agent installed-status` 验证主服务与运行时版本及设置可读性。

环境开关：`ROAMI_VERSION=vX.Y.Z`、`ROAMI_BIN_DIR=DIR`、`ROAMI_INSTALL_ROOT=DIR`、`ROAMI_SYSTEM=1`（系统级服务，需 sudo）、`ROAMI_NO_SERVICE=1`（安装完整环境后手动运行 `roami`）。离线安装可设置 `ROAMI_BUNDLE_FILE=/path/roami-linux-amd64.tar.gz`，同目录需有对应 `.sha256`；tmux 等宿主工具仍需预先准备。

### 方式 B — 手动跑二进制

只需前端与会话核心时，可到 [Releases](https://github.com/ybz21/Roam/releases) 下载裸二进制。内置智能体及其设置需要完整包；若只是不想注册服务，使用 `ROAMI_NO_SERVICE=1` 的安装方式。

```bash
# 例：Linux x86_64
curl -fsSL -o ~/.local/bin/roami \
  https://github.com/ybz21/Roam/releases/latest/download/roami-linux-amd64
chmod +x ~/.local/bin/roami
roami                    # 启动 Web 控制台，监听 0.0.0.0:13579
```

### 方式 C — 从源码（开发）

```bash
git clone https://github.com/ybz21/Roam.git
cd Roami
./start.sh --dev       # 从源码构建 CLI/chrome/skills + 前端 + 后端，然后启动
```

`start.sh` 还支持 `stop` / `status` / `logs` / `fg`；不带 `--dev` 直接启动已构建产物。

首次启动**没有口令**：在浏览器打开控制台先设一个再进入。之后可在**「设置 → 安全」**
或编辑 `~/.roami/config.yaml` 修改。默认监听 `0.0.0.0:13579`（自签 HTTPS——麦克风和
剪贴板需要安全上下文），局域网设备可直接访问。远程访问建议走 Tailscale、
Cloudflare Tunnel、SSH forwarding 或 frp。

通过 **frp 暴露并保持 HTTPS**（让手机语音输入、剪贴板经隧道仍可用）的配置见
**[docs/deploy/frp.md](docs/deploy/frp.md)**（中英双语）。

完整安装、部署、远程访问和命令行自动化说明见 **[docs/install/](docs/install/)**。

## 不止一台机器

单机的 Roami 本身就是完整产品；只有当你有第二台机器时才需要这一节。每台机器照样自己
跑会话、Agent 和文件，中心只负责把请求路由过去——除了「从外面能不能连上」，机器的
任何能力都不依赖中心活着。

**中心**就是同一个二进制以中心模式启动。它不跑会话、不跑 Agent、不跑浏览器，
只有注册表、控制台和隧道：

```yaml
# 中心机器的 ~/.roami/config.yaml
cluster:
  mode: hub
  public_url: https://roami.example.com    # 机器要拨过来用的那个地址
```

**每台机器**用一次性接入令牌（在**「设置 → 多机」**里签发）主动拨向中心，
之后换成长期凭证：

```yaml
# 各台机器的 ~/.roami/config.yaml
cluster:
  hub: https://roami.example.com
  token: <一次性接入令牌>
  name: workstation                        # 显示名，默认取 hostname
```

因为隧道是**出站**建立的，NAT 或家用路由器后面的机器不需要做端口转发。接上之后：

- 控制台里的切机器（手机上在**「更多」**里）会把整个工作区搬到另一台机器上——终端标签
  按机器各记各的，切回来还是原来那几个会话；
- **中心页**给出中心健康、每台机器的延迟/CPU/内存/会话数，以及掉线与重连的事件流；
- 某台机器的曲线一路往上爬时，侧栏那枚按钮上会亮红点——健康判据看的是曲线**形状**而不是
  绝对阈值，所以机器大一点不会误报；
- 任意机器上的**「完整监控」**打开的，就是 `roam.host-monitor` 插件在本机画的那块面板——
  CPU、GPU、磁盘、网络和历史曲线。

## 给 Claude Code / Codex 用

如果开发机上装了 Claude Code、Codex 或其他命令行编程工具，项目页是用它们最快的
方式：描述任务，Agent 就在独立 worktree、独立分支上开干，并行任务互不踩脚；还可以
让 Claude Code 和 Codex 竞赛同一任务，对比后择优采纳。当然也可以直接在 Roami 的
持久终端里运行任何工具。执行过程、输出、上下文和后续指令入口都留在开发机上；
你从手机或平板回来时，可以继续读它跑到哪里，也可以继续追加要求。

更复杂的任务拉起一个蜂群，拆成多个成员：有人负责 API，有人负责前端，有人负责测试；
共享看板和消息流用于同步进度，依赖完成后再解锁下一步。

## 命令行和自动化

Roami 也提供命令行入口，方便脚本、自动化流程和 AI Agent 调用。这里不是普通用户的
主入口；大多数时候你可以先从 Web 控制台开始。

- `roami session`：管理持久会话、后台任务、Agent worker、swarm 和机器可读状态。
- `roami chrome`：驱动开发机上的 Chrome，用于 UI 调试、截图、表单操作和自动化验收。
- `roami adb`：转发系统 ADB，用于 Android 截图、触控、App 操作、文件传输和设备调试；需已安装 ADB。

插件则扩展控制台本身——`roam.host-monitor` 提供资源监控面板，`roam.cron` 提供定时
prompt 并自带配置面板。

命令细节不放在首页展开，避免 README 变成工具手册。需要时请看
**[docs/install/](docs/install/)**、`roami session help`、`roami chrome help` 和 `roami adb help`。

## 开发与贡献

每个 clone 只需安装一次仓库 Git hooks：

```bash
bash scripts/dev/install-git-hooks.sh
```

pre-commit hook 会运行快速质量门禁；CI 会在 push 和 pull request 上运行完整门禁：

```bash
scripts/dev/quality/check.sh quick
scripts/dev/quality/check.sh full
```

构建并运行 Web 控制台：

```bash
./start.sh --dev fg
```

只跑前端：

```bash
cd frontend
npm install
npm run dev
```

只跑后端：

```bash
TTMUX_WEB_PASSWORD=dev go run ./cmd/roami server
```

CLI smoke test：

```bash
ROAMI_BIN=/tmp/roami bash tests/test-session-cli.sh
```

给 Agent 的仓库规则（设计系统、i18n、质量门禁）都在
**[AGENTS.md](AGENTS.md)**——Codex 和 Claude Code 读的是同一份。

## 安全说明

Roami 能操作你开发机上的终端、文件、浏览器和 Agent，请把它当作接近 SSH 的权限对待。
正式部署时：

- 使用强口令，必要时开启两步验证。
- 外网访问优先走 Tailscale、Cloudflare Tunnel、SSH forwarding 或 frp。
- 不要把 Web 控制台端口直接暴露在公网。
- 接入令牌是一次性的且会过期（默认 30 分钟）；机器之后持有长期凭证，中心只存它的哈希。
- 诊断端口（`ROAMI_PPROF`）默认关闭，且只允许绑回环地址。
- 只在你信任的机器和账号上运行。

## 文档

- [docs/features.zh-CN.md](docs/features.zh-CN.md) - 完整功能清单
- [docs/install/](docs/install/) - 安装与部署
- [docs/design/](docs/design/) - 蜂群编排、广场看板、多机拓扑与 Web 集成的设计文档
- [backend/README.md](backend/README.md) - 后端实现细节

## 许可证

GNU Affero General Public License v3.0 (AGPL-3.0)。见 [LICENSE](LICENSE)。
