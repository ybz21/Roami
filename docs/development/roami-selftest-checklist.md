# Roami 自检清单

**每天凌晨 2:00 由定时任务跑一遍**（`roam.cron` 里的 `roami-自检`），也可以随时手动跑：出了
奇怪的问题时，先照这张单子过一遍，比凭印象猜快。

清单分两半，界线是**能不能不看屏幕就判对错**：

| | 谁来跑 | 怎么跑 |
| --- | --- | --- |
| 机器那一半 | 脚本 | `scripts/dev/selftest/roami-selftest.sh [--remote]` |
| 眼睛那一半 | Agent 开浏览器 | 本文 §2，用 playwright 连本机实例逐项看 |

判定：脚本有 `FAIL` 就是坏了；`WARN` 是「值得看一眼但不一定是故障」（版本不齐、磁盘偏满）。
§2 每条都写明了**期望**，对不上就记进报告，别自己说服自己。

---

## 1. 机器那一半（脚本已覆盖）

`scripts/dev/selftest/roami-selftest.sh` 逐条打 PASS/FAIL/WARN，有 FAIL 时退出码非 0：

- **服务**：`/api/version` 通、版本不是 `vdev`（`vdev` = 手动 `go build` 丢了 ldflags）；
  `roami.service` 是 active。
- **登录**：拿 `~/.roami/config.yaml` 里的口令走 `/api/login`，能拿到 cookie。
  口令只读不打印。
- **核心接口**：`/api/sessions`、`/api/projects`、`/api/plugins`、`/api/preferences`、
  `/api/browser/config` 都返回**合法 JSON**并能取到关键字段。
- **插件**：`host-monitor.stats` 出得来 CPU 数、`cron.list` 出得来任务数。这两条顺带守住
  「插件日志混进 JSON」那条回归（`[roam.cron] …` 曾把整份响应弄成非 JSON）。
- **tmux 底座**：tmux server 活着、`_ttmux-plugind` 在（它不在，插件的定时/常驻全停摆）、
  `roami session ls --json` 读得出台账。
- **前端产物**：首页 HTML 引得到 `/assets/*.js` 且该文件 200（dist 没构建 / `-web` 指错目录
  会在这里露馅）。
- **定时任务巡检**：`roami-cron-tick.timer` 在跑（或有人常驻 `cron.serve`）。插件宿主**没有**
  内置调度器，到点触发全靠外面每分钟叫一次 `ttmux plugin run cron.tick`；这条断了，
  所有定时任务只是躺在库里——包括这份自检本身。装法：

  ```bash
  cp scripts/deploy/systemd/roami-cron-tick.{service,timer} ~/.config/systemd/user/
  systemctl --user daemon-reload && systemctl --user enable --now roami-cron-tick.timer
  ```
- **容量**：磁盘、内存 <90%。
- `--remote`：jetson 与阿里云的版本和本机是否一致（不一致只报 WARN——常常只是还没部署）。

## 2. 眼睛那一半（Agent 用浏览器跑）

用真 Chrome 连 `https://localhost:13579`（自签证书要 `ignoreHTTPSErrors`），口令同上。
桌面档 1600×950；手机档 392×844 + `deviceScaleFactor: 2.75` + `hasTouch`。
每条给一句结论，附截图路径；失败项要写清「看到的是什么」。

### 2.1 首屏与左树
- [ ] 登录后进项目页，不白屏、无 500。
- [ ] 左树能看到项目 → 任务 → 会话三层；点项目行能展开/收起，刷新后**记得**上次的展开状态。
- [ ] `_ttmux-plugind`、`_ttmux-*` 这类基础设施会话**不出现**在树里。
- [ ] 互审陪跑（`<id>-review`）挂在被审那条下面，显示「互审 · 谁」，不是一串 id。
- [ ] 单会话任务只占**一行**（不是任务、会话各一行同名）；右键菜单里
      重命名只有一枚、红色动作只有一枚。

### 2.2 终端
- [ ] 点开一个会话，终端出画面、能输入、回显正常。
- [ ] 标签多于一屏时左右翻页钮可用，点某个标签会把它滚到中间。
- [ ] 工具条「重绘」能修花屏（窄屏 ink TUI 抖尺寸那条）。

### 2.3 对话（Claude / Codex）
- [ ] 切到对话视图能看到消息流；状态条有模型、上下文占用。
- [ ] 输入行「+」打开：权限模式那行显示的档位**和终端页脚一致**；模型、上下文占用有值。
- [ ] 在档位表里点另一档，2 秒内落到那一档，终端页脚同步变（验完切回原档）。
- [ ] 发一句话能到 agent（`roami session send` 那条路），不是只打字不回车。

### 2.4 文件与 Git
- [ ] 文件页能列目录、打开文件、平铺/VSCode 两种布局都能切。
- [ ] 拖一个文件到对话输入框，插进去的是 `@绝对路径`，不是重复路径或空值。
- [ ] Git 面板能看到分支、改动、diff。

### 2.5 镜像（浏览器 / 手机）
- [ ] 浏览器镜像出画面，能点、能输网址；拖动分栏只改缩放，页面**不重排**。
- [ ] 全屏进出正常，全屏里下拉菜单还在（浮层要挂在全屏元素里）。
- [ ] 手机镜像出画面；`chrome://*top-chrome*` 这类系统标签不出现在标签列表里。

### 2.6 插件页与状态条
- [ ] 插件页四个插件都在、开关状态正确、卸载/恢复按钮在。
- [ ] 定时任务：新增一条 → 弹的是「已添加任务」，表格当场多一行；改、启停、删都生效。
      （这条能挡住 stdout/stderr 混流那类回归——报错会是一句 JSON 解析失败）
- [ ] 底部状态条六格（CPU/内存/磁盘/温度/GPU/网络）都在，数值会动；点某格能到对应页面。

### 2.7 手机档
- [ ] 392 宽下底部导航、会话切换面板可用。
- [ ] 图标按钮命中区 ≥44px，相邻两枚之间点不空。
- [ ] 点过的按钮不残留 hover 高亮（`:hover` 全部锁在 `data-pointer="fine"`）。
- [ ] 页面本身不出现横向滚动条（`html, body { overflow: hidden }`）。

## 3. 产出

- 报告写到 `~/.roami/selftest/<YYYY-MM-DD>.md`：首行是
  `PASS n · FAIL n · WARN n`，然后是脚本原样输出，再是 §2 逐条结论与截图路径。
- 有 FAIL：把失败项摘要发一份 IM（`ttmux plugin run im-bridge.send`，没绑就跳过），
  并在报告顶部标红。
- 自检**只读不改**：不许改配置、不许关别人的会话、不许动 worktree。
  §2.3 那条切档位是唯一的写操作，验完必须切回原档。
