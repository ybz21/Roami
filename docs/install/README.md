# 安装与部署

ttmux 有 **两种使用模式**，按需取用，也可叠加：

| 模式 | 场景 | 装什么 | 必需依赖 |
|------|------|--------|----------|
| **① 本地 CLI** | 在终端 / 服务器上直接编排并行任务、Agent、蜂群 | `ttmux` 单文件二进制 | `tmux`（Claude Code 按需） |
| **② 远程控制台** | **远程办公**：手机 / 平板 / 笔记本随地查看·操控（实时终端 + 浏览器镜像） | `roami` 预构建单文件二进制（内嵌前端 + 统一会话核心）+ frp 内网穿透 | 目标机零依赖（`go`、`node`+`npm` 仅从源码构建时才需要；远程暴露用 frp） |

> 模式 ② 跑在你的开发机 / 长期常驻的机器上，模式 ① 是它的底座——**远程控制台本质是 CLI 的网页封装**，
> 读 = 代理 `ttmux <cmd> --json`，写 = 调对应子命令，行为与 CLI 永远一致。`roami` 二进制已把
> 前端和 `ttmux` CLI 一并内嵌，目标机无需 go/node/npm（仅从源码构建时才需要）。
>
> 只在终端用 → 只装 [① CLI](#一本地-cli)。要随地远程控制 → 再加 [② 远程控制台](#二远程控制台) + [frp 远程办公](#四远程办公--frp-内网穿透)。

- [一、本地 CLI](#一本地-cli)
- [二、远程控制台](#二远程控制台)
- [三、配置项（config.yaml）](#三配置项configyaml)
- [四、远程办公 —— frp 内网穿透](#四远程办公--frp-内网穿透)
- [五、可选能力](#五可选能力)
- [六、升级与卸载](#六升级与卸载)
- [七、故障排查](#七故障排查)

---

## 依赖速查

> 默认安装下载完整包，携带独立 Python、智能体 wheel 及全部生产依赖（含时区数据）；在目标目录创建 venv，无需用户预装 Python、uv、Go 或 Node。裸二进制不含 Python 运行时，不能单独提供内置智能体。
> 下表标「仅源码构建」的两项，用预构建二进制时可略过。

| 依赖 | 用途 | 没有它会怎样 | 安装 |
|------|------|--------------|------|
| `tmux` | CLI / 会话的运行基座 | 会话无法工作（`roami` 集成会话核心，但仍需宿主机装 `tmux`） | `apt install tmux` / `brew install tmux` |
| Claude Code | `spawn --agent` / 蜂群成员 | 仅 Agent 类任务不可用 | 见 [claude.ai/code](https://claude.ai/code) |
| `go` ≥ 1.21 | **仅源码构建**：编译 CLI + Web 后端 | 只影响 `start.sh --dev`；预构建二进制无需 | [go.dev/dl](https://go.dev/dl/) |
| `node` ≥ 18 + `npm` | **仅源码构建**：构建前端 + `chrome` 自动化 | 只影响 `start.sh --dev` / `chrome`；预构建二进制无需 | [nodejs.org](https://nodejs.org/) |
| `google-chrome` | 浏览器镜像页 + `chrome` 自动化 | 「浏览器」标签 / `chrome` 不可用 | 系统包管理器 |

---

## 一、本地 CLI

安装后的正式 CLI 为 `roami`，会话、浏览器、项目与数据库都从这里访问。安装器为旧 `ttmux`、`chrome`、`roam` 命令保留兼容入口；它们指向同一应用，不再解压第二份会话二进制。

```bash
roami session help
roami chrome help
roami project help
roami db status --json
```

源码构建在仓库根目录执行：

```bash
CGO_ENABLED=0 go build -o ~/.local/bin/roami ./cmd/roami
ln -sf roami ~/.local/bin/ttmux
ln -sf roami ~/.local/bin/chrome
mkdir -p ~/.local/share/bash-completion/completions
roami completion > ~/.local/share/bash-completion/completions/roami
export PATH="$HOME/.local/bin:$PATH"
```

数据库默认位于 `~/.roami/database/`，备份位于 `~/.roami/backups/`。旧版数据库不自动移动；安装器发现旧布局时会保留候选 `roami.upgrade`，在替换现有程序和兼容入口之前停止安装。使用候选程序先只读盘点，停止服务及所有旧插件/CLI 写者后才执行离线迁移；完成后重新安装：

```bash
roami db migrate --layout --dry-run
# 确认全部旧写者已停止后执行；保留旧源库和 pre-layout 备份。
roami db migrate --layout --offline
```

全新实例可用 `roami db migrate` 初始化。完整备份与恢复：

```bash
# 当前完整备份要求停止服务与插件宿主，活跃实例会返回 STORAGE_BUSY。
roami db backup /path/to/backup-set
# 恢复目标必须是空实例，包含布局与 catalog 元数据，并校验数据库 hash。
roami --home /new/home --data-dir /new/data --database-dir /new/data/database db restore /path/to/backup-set
# 发布中断时保留 journal 和 staging，显式完成恢复。
roami db migrate --recover
```

CLI 和服务必须使用同一组 Home/Data/DatabaseRoot；配置可用 `storage.data_dir`、`storage.database_dir`、`storage.backup_dir`，或正式 `ROAMI_*` 路径变量覆盖。开发隔离使用 `scripts/dev/isolated-roami.sh`，不能只设置 ROAMI_HOME 后继承旧 DATA/DATABASE_DIR。

### 4. 验证

```bash
roami session help
roami session new dev
roami session spawn build "lint" "echo ok" "test" "echo pass"
roami session status build
```

---

## 二、远程控制台

远程控制台使用完整包 `roami-<os>-<arch>.tar.gz`（linux/darwin，amd64/arm64），内含主程序、前端、独立 Python 和智能体生产依赖；裸二进制资产继续提供给只使用会话核心的高级用户。配置与数据都在 `~/.roami/`（`config.yaml` 首次运行自动生成）。装在你的开发机 / 长期常驻的机器上，本节先让它在本机 / 局域网跑起来；要从外网随地访问，见 [四、远程办公](#四远程办公--frp-内网穿透)。

三种装法，任选其一：

### 方式 A · 一键脚本（推荐，装二进制 + 常驻服务）

```bash
curl -fsSL https://raw.githubusercontent.com/ybz21/Roam/main/install.sh | bash
```

`install.sh` 是**常驻安装器**（适合 24 小时运行的机器）：检测 OS/架构 → 下载 `roami-<os>-<arch>` 到 `~/.local/bin/roami` → 注册 **systemd** 服务并启动。环境开关：

- `ROAMI_VERSION=vX.Y.Z` —— 指定版本（默认 latest）。
- `ROAMI_BIN_DIR=DIR` —— 安装目录（默认 `~/.local/bin`）。
- `ROAMI_SYSTEM=1` —— 注册**系统级** systemd 服务（`/etc/systemd/system`，需 root/sudo）。
- `ROAMI_NO_SERVICE=1` —— 只装二进制，不注册服务。
- `ROAMI_FROM_SOURCE=1` —— 在 clone 内从源码构建（需 go+node），而非下载 release。

服务管理：

```bash
systemctl --user status roami       # 状态（系统级用 sudo systemctl status roami）
systemctl --user restart roami      # 重启
systemctl --user stop roami         # 停止
```

### 方式 B · 手动跑二进制（不注册服务）

```bash
# 以 linux amd64 为例，按你的系统/架构替换资产名
curl -fSL -o ~/.local/bin/roami \
  https://github.com/ybz21/Roam/releases/latest/download/roami-linux-amd64
chmod +x ~/.local/bin/roami
roami                               # 直接前台运行
```

### 方式 C · 从源码构建

```bash
git clone https://github.com/ybz21/Roam.git
cd Roami
./start.sh --dev                   # 从源码构建 CLI/chrome/skills + 前后端，再启动
```

`./start.sh --dev` 在 clone 内从源码构建 ttmux CLI + chrome CLI + skills + 前端 + 后端，再运行；`start.sh` 不再调用 `install.sh`。**已构建过产物**后，直接 `./start.sh`（不带 `--dev`）即可跑现有产物。

无论哪种方式，启动后都会打印访问地址：

```
==> 启动 Roami  https://0.0.0.0:13579
==> 手机/平板（同 WiFi）: https://192.168.x.x:13579
```

浏览器打开该地址：**首次启动口令为空**，在 Web 界面里设置口令后即可进入（之后可在 **设置 → 修改密码** 或 `~/.roami/config.yaml` 的 `web.password` 里改）。TLS 默认开启（自签 HTTPS，手机经局域网用麦克风/剪贴板需安全上下文）。

> 增量构建（`--dev`）：前端/后端**有改动才重新编译**，没改动直接复用产物，二次启动很快。

### 进程管理

```bash
# 方式 A（systemd 服务）
systemctl --user status roami       # 状态（系统级用 sudo systemctl …）
systemctl --user restart roami      # 重启 / stop 停止
journalctl --user -u roami -f       # 跟随日志

# 方式 C（源码 / 开发启动器 start.sh）
./start.sh stop      # 停止
./start.sh status    # 查看是否在跑 + 端口/PID
./start.sh logs      # 跟随日志（tail -f）
./start.sh --dev fg        # 前台运行（调试用，Ctrl-C 即停）
```

### 手动运行（不用脚本，源码调试）

```bash
# 前端构建一次
cd frontend && npm install && npx vite build && cd ..

# 后端编译并运行（flag 覆盖配置；口令来自 config.yaml / 首次运行界面设置）
go build -o backend/ttmux-web ./cmd/roami
TTMUX_BIN=../ttmux \
  ./ttmux-web -addr 127.0.0.1:13579 -web ../frontend/dist
```

### 开发模式（前后端分离热更新）

```bash
 go run ./cmd/roami server   # 后端 :8080（口令来自 config.yaml）
cd frontend && npm run dev                        # 前端 :5173（代理 /api 含 WS）
```

后端分层与 API 见 [`../../backend/README.md`](../../backend/README.md)，完整设计见 [`../design/web/`](../design/web/)。

---

## 三、配置项（config.yaml）

配置现在集中在 **`~/.roami/config.yaml`**，首次运行时从内置模板自动生成（仓库内参考副本见 [`../../configs/config.yaml.template`](../../configs/config.yaml.template)）。生效优先级为 **命令行 flag > 环境变量 > 配置文件 > 默认值**。

环境变量现在主要用 `ROAMI_*` 前缀（如 `ROAMI_WEB_PASSWORD`、`ROAMI_WEB_BIND`）；为兼容旧版，**`TTMUX_*` 别名（`TTMUX_WEB_PASSWORD`、`TTMUX_WEB_BIND` 等）仍然被识别**。

| 配置项 / 环境变量 | 默认 | 说明 |
|------|------|------|
| `web.password` / `ROAMI_WEB_PASSWORD`（旧：`TTMUX_WEB_PASSWORD`） | 留空 | 登录口令。**首次启动为空**：打开 Web 控制台后在界面里设置口令再进入（不再随机生成写回文件）。之后可在 **设置 → 修改密码** 里改，或直接编辑 `~/.roami/config.yaml` 的 `web.password`。**务必用强口令。** |
| `web.bind` / `ROAMI_WEB_BIND`（旧：`TTMUX_WEB_BIND`） | `0.0.0.0:13579` | 监听地址。`0.0.0.0` = 局域网可达；`127.0.0.1` = 仅本机。 |
| `web.tls` | `true` | 是否启用自签 HTTPS（手机经局域网用麦克风/剪贴板需安全上下文）。 |
| `web.tls_san` | `[]` | 自签证书追加的 SAN 列表。 |
| `TTMUX_BIN` | `start.sh` 设为仓库内 `./ttmux` | 后端调用的 ttmux 路径。 |
| `web.two_fa` / `ROAMI_WEB_2FA`（旧：`TTMUX_WEB_2FA`） | 关闭 | 设为 `off/0/false/no` 让初始 TOTP 种子失效；两步验证也可在控制台「系统配置」里开关。 |
| `web.totp_secret` / `ROAMI_WEB_TOTP_SECRET`（旧：`TTMUX_WEB_TOTP_SECRET`） | 空 | 两步验证密钥初始种子（base32）；启用后状态以 `totp.json` 为准。 |
| `web.lock_after` / `ROAMI_WEB_LOCK_AFTER`（旧：`TTMUX_WEB_LOCK_AFTER`） | `10` | 连续登录失败多少次后锁定。 |
| `web.lock_secs` / `ROAMI_WEB_LOCK_SECS`（旧：`TTMUX_WEB_LOCK_SECS`） | `30` | 锁定时长（秒）。 |
| `ROAMI_DATA`（旧：`TTMUX_DATA`） | `~/.roami` | 数据目录（日志、`totp.json` 等）；旧的 `~/.ttmux`、`~/.local/share/ttmux` 首次运行会自动迁移过来。 |
| `TTMUX_CHROME_CDP` | `http://127.0.0.1:9222` | 浏览器镜像对接的 Chrome 调试端口。 |
| `TTMUX_CHROME_SCALE` | `2` | 浏览器镜像渲染像素密度（越大越清晰、越吃带宽）。 |
| `TTMUX_WEB_LOG` | `/tmp/ttmux-web.log` | 守护进程日志路径（仅 `start.sh`）。 |
| `TTMUX_WEB_PID` | `/tmp/ttmux-web.pid` | 守护进程 PID 文件（仅 `start.sh`）。 |

`~/.roami/config.yaml` 示例：

```yaml
web:
  password: ""            # empty = set it in the Web UI on first launch
  bind: 0.0.0.0:13579
  tls: true
  tls_san: []
  totp_secret: ""
  two_fa: ""
  lock_after: 10
  lock_secs: 30
```

---

## 四、远程办公 —— frp 内网穿透

家里/公司的开发机一般没有公网 IP，外网到不了。**frp** 用一台有公网 IP 的小服务器做中转，把内网的控制台穿透出来——这是远程办公最常用、自托管、零依赖第三方的方案。

```
 手机/笔记本(外网) ──► 公网服务器 frps ──► 内网开发机 frpc ──► roami (127.0.0.1:13579)
```

> ⚠ **远程控制台等于把 shell 执行能力搬上网。** 穿透前务必编辑 `~/.roami/config.yaml`：设强
> `web.password` + 开两步验证（控制台「系统配置」）+ 保留登录失败锁定（`web.lock_after` /
> `web.lock_secs`）。并把 `web.bind` 收回 `127.0.0.1:13579`，只让 frpc 在本机连，不再裸暴露局域网。

下载 frp：[github.com/fatedier/frp/releases](https://github.com/fatedier/frp/releases)（`frps` 放公网服务器，`frpc` 放开发机）。

**公网服务器**　`frps.toml`：

```toml
bindPort = 7000
auth.token = "<TOKEN>"     # 换成强随机串，frps/frpc 必须一致
```

```bash
./frps -c frps.toml        # 放进 systemd / nohup 常驻
# 记得在云厂商安全组放行 7000，以及下方要用的对外端口
```

### 方案 A · 简单（对外开一个端口）

**开发机**　`frpc.toml`：

```toml
serverAddr = "公网服务器IP"
serverPort = 7000
auth.token = "<TOKEN>"   # 与 frps 相同

[[proxies]]
name = "ttmux-web"
type = "tcp"
localIP = "127.0.0.1"
localPort = 13579        # 对应 web.bind
remotePort = 13579       # 公网服务器对外端口
```

```bash
./frpc -c frpc.toml
```

浏览器/手机访问 `http://公网服务器IP:13579` 即可。手机也能用——这是远程办公最省事的路子。
代价：公网上有一个开放端口，**安全全靠控制台自身的口令 + 2FA**，请务必开齐。

### 方案 B · 推荐（不开任何公网端口，stcp 点对点）

`stcp` 加密隧道在公网**不监听端口**，只有持密钥的「访客端」能连——更适合长期远程办公。

**开发机**　`frpc.toml`：

```toml
serverAddr = "公网服务器IP"
serverPort = 7000
auth.token = "<TOKEN>"   # 与 frps 相同

[[proxies]]
name = "ttmux-web"
type = "stcp"
secretKey = "再换一串强随机密钥"   # 访客端要一致
localIP = "127.0.0.1"
localPort = 13579
```

**你的笔记本（访客端）**　`frpc-visitor.toml`：

```toml
serverAddr = "公网服务器IP"
serverPort = 7000
auth.token = "<TOKEN>"   # 与 frps 相同

[[visitors]]
name = "ttmux-web-visitor"
type = "stcp"
serverName = "ttmux-web"
secretKey = "同上面的 secretKey"
bindAddr = "127.0.0.1"
bindPort = 13579        # 映射到本机
```

```bash
# 开发机
./frpc -c frpc.toml
# 笔记本
./frpc -c frpc-visitor.toml
```

之后在笔记本上访问 `http://127.0.0.1:13579`——流量端到端加密，公网无暴露端口。
（缺点：访客端要跑 frpc，手机不便；手机场景用方案 A，或给 frps 配 `vhostHTTPSPort` + 域名走 https。）

### 替代方案

不想自己备公网服务器，也可用现成隧道：

- **Tailscale**：组网后用设备 tailnet IP 访问 `http://<tailscale-ip>:13579`，仅你的网络内可达，零端口暴露。
- **Cloudflare Tunnel**：`cloudflared tunnel --url http://127.0.0.1:13579`，把 `~/.roami/config.yaml` 的 `web.bind` 收回 `127.0.0.1`。

---

## 五、可选能力

### 浏览器镜像

「浏览器」标签把服务器上的一台 Chrome 实时投屏到网页（CDP screencast + 可接管输入 + 多 tab + F12 调试）。需要 `google-chrome` 可执行：

- 后端会在 `TTMUX_CHROME_CDP`（默认 `127.0.0.1:9222`）探测；端口没有 Chrome 时**自动拉起**一个带远程调试端口的实例（无显示器时自动 `--headless=new`）。
- 已有 Chrome 跑在该端口（如 Agent 自己起的）则直接附着，不重复拉起。
- 想清晰一点/省带宽一点，调 `TTMUX_CHROME_SCALE`。

### 浏览器自动化 —— `chrome`（独立 CLI）

`chrome` 是 ttmux 家族里**独立的浏览器自动化 CLI**（不是 `ttmux` 子命令），引擎是 **Playwright over CDP**。它 `connectOverCDP` 接的就是上面那台全局 Chrome（`TTMUX_CHROME_CDP`），所以**自动化能在 Web「浏览器」标签里实时围观**；没起 web 后端时，本命令也会按同一套 flag 自己拉起 Chrome。

依赖 `node` + `npm`，`install.sh` 会随 `chrome` 一起 `npm i playwright-core`（`connectOverCDP` 复用已开的 Chrome，**不下载 Playwright 自带浏览器**，很轻）。手动或重装：

```bash
roami chrome setup                       # 安装/更新依赖（node + playwright-core）
roami chrome goto https://example.com    # 打开网址
roami chrome text h1                      # 取文本
roami chrome eval "document.title"        # 页面内执行 JS
roami chrome screenshot shot.png --full   # 整页截图
roami chrome screenshot shot.png --fresh --goto https://example.com --viewport 1280x800
roami chrome tabs                         # 列标签页
roami chrome help                         # 全部动词与选项
```

动词：`goto / click / fill / type / press / text / html / attr / eval / wait / screenshot / pdf / tabs / new / close`；
通用选项 `--tab <序号>` / `--url <子串>` 选目标标签页、`--timeout <ms>`、`--cdp <地址>`。
批量截图优先用 `--fresh --goto <url>`；需要复用已登录状态或在 Web「浏览器」标签围观时再用默认共享 Chrome。
源码与开发见 [`../development/chrome-cli.md`](../development/chrome-cli.md)。

---

## 六、升级与卸载

**升级**：

- 服务安装（方式 A）：重跑 `curl -fsSL https://raw.githubusercontent.com/ybz21/Roam/main/install.sh | bash` 覆盖即可，或指定版本 `ROAMI_VERSION=vX.Y.Z bash install.sh`。
- 源码构建（方式 C）：`git pull && ./start.sh --dev`（脚本检测改动并重编）。

**卸载**：

```bash
systemctl --user disable --now roami           # 停并停用服务（系统级用 sudo systemctl …）
rm -f ~/.config/systemd/user/roami.service     # 移除服务单元
rm -f ~/.local/bin/roami ~/.local/bin/ttmux    # 二进制（roami + 若单独装过的 ttmux）
rm -rf ~/.roami                                # 配置 + 数据 + 蜂群 meta.db（现全在一个目录下）
```

（若之前单独装过 Claude Code skills，可另行删 `~/.claude/skills/ttmux/` 等目录。）

---

## 七、故障排查

| 现象 | 排查 |
|------|------|
| `command not found: ttmux` | `~/.local/bin` 不在 `PATH`，按[一、本地 CLI](#一本地-cli) 追加；或把 `~/.local/bin/roami` 软链出来。 |
| `command not found: roami` | `~/.local/bin` 不在 `PATH`，追加 `export PATH="$HOME/.local/bin:$PATH"`。 |
| 装 `roami` 报缺 go/node | 预构建二进制**无需**任何运行时依赖；只有从源码构建（`./start.sh --dev` / `ROAMI_FROM_SOURCE=1`）才需要 go+node，直接用一键脚本下载二进制即可。 |
| 启动报「需要先安装 tmux」 | 装 `tmux`（`roami` 集成会话核心，但会话仍需宿主机的 `tmux`）。 |
| 后端日志「找不到 ttmux」 | `TTMUX_BIN` 没指对，或 ttmux 不在 PATH。新版本会话能力已编入 Roami；重新运行安装器刷新兼容入口，源码开发在根目录构建 `./cmd/roami`。 |
| 端口被占用 / 想换端口 | 改 `~/.roami/config.yaml` 的 `web.bind`，或停掉旧进程（`systemctl --user restart roami` / `./start.sh stop`）。 |
| 前端是「内嵌回退页」很简陋 | 源码运行时说明没构建 React，跑 `./start.sh --dev`；预构建 `roami` 已内嵌前端，不会出现。 |
| 浏览器标签连不上 | 确认装了 `google-chrome`；检查 `TTMUX_CHROME_CDP` 指向的端口。 |
| 忘了口令 | 在控制台 **设置 → 修改密码** 里改；或编辑 `~/.roami/config.yaml` 的 `web.password` 后 `./start.sh stop && ./start.sh`。 |
| 看后端日志 | `./start.sh logs`（默认 `/tmp/ttmux-web.log`）。 |
