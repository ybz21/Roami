// Package server 装配 Gin 引擎：注册中间件与路由，挂载前端。
//
// 前端（React + Vite）是独立项目（仓库根 frontend/），不放在后端目录内。
// 后端从磁盘提供其构建产物 frontend/dist（路径由 Config.FrontendDir 指定）；
// 未构建/找不到时回退到后端自带的内嵌单页 fallback.html。
package server

import (
	_ "embed"
	"encoding/json"
	"log"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"ttmux-web/api"
	"ttmux-web/auth"
	"ttmux-web/browser"
	"ttmux-web/cluster/node"
	"ttmux-web/config"
	"ttmux-web/home"
	"ttmux-web/p2p"
	"ttmux-web/phone"
	"ttmux-web/pty"
	"ttmux-web/stream"
	"ttmux-web/ttmux"
)

//go:embed fallback.html
var fallbackHTML []byte

type Config struct {
	TTmuxBin string
	// EmbeddedBin 是内嵌的那份 ttmux（release 构建才有真货）。台账握手失败时用它
	// 重试一次——救「PATH 上残留一个老 ttmux，而 roam 二进制是新的」这种情况。
	EmbeddedBin  string
	LogsDir      string
	FrontendDir  string // frontend/dist 的路径；为空或不存在时用内嵌回退页
	BrowserHome  string // 浏览器导航起始页地址（供 Chrome 当默认主页）
	DataDir      string // 数据目录（导航页站点列表等持久化到此）
	TLSCertPath  string // 自签证书路径（供「下载证书」端点下发；TLS 关闭时为空）
	Password     string
	TOTPSecret   string // 可选：两步验证密钥（base32）初始种子；UI 可覆盖
	TOTPState    string // 两步验证状态持久化文件路径
	LockAfter    int
	LockSecs     int
	SavePassword func(string) error // 把登录口令落盘到 config.yaml（首次设置/改密用）
	Version      string             // roam 版本号（关于页展示 + 检测更新）

	// P2P 直连（M0a spike）：灰度开关 + STUN/TURN 服务列表。
	P2PEnabled    bool
	P2PICEServers []string
	// M0b 跨网穿透杠杆（默认值等价 M0a 行为）：固定 UDP 端口 / UPnP 映射 / mDNS。
	P2PUDPPort int
	P2PUPnP    bool
	P2PMDNS    bool

	// 多机（设置页要读要写）：配置文件路径、当前 cluster 段、以及 standard 模式下
	// 那个隧道客户端（用来报接入状态）。单机时后两者为零值，设置页照样显示得出来。
	ConfigPath string
	Cluster    config.Cluster
	NodeClient *node.Client
	Bind       string
	TLSEnabled bool
}

func New(cfg Config) *gin.Engine {
	gin.SetMode(gin.ReleaseMode)
	r := gin.New()
	r.UseRawPath = true
	r.Use(gin.Recovery())

	tt := ttmux.New(cfg.TTmuxBin)
	a := auth.New(cfg.Password, cfg.TOTPSecret, cfg.TOTPState, cfg.LockAfter, cfg.LockSecs, cfg.SavePassword)
	h := api.New(tt, cfg.BrowserHome, cfg.DataDir, cfg.EmbeddedBin)
	go h.SyncLoop()                 // 后台兜底远端同步（10 §3 第三档），失败静默
	go h.AgentLinkLoop()            // 会话 ↔ claude 对话 id 对账、归属跟着 worktree 走（api/session-home-sync.go）
	h.SyncClaudeThemeOnce()         // Claude Code 主题对齐 Roami 主题（api/claude-theme-sync.go）
	go h.SessionEventLoop()         // 「会话在等你」→ 收件箱 + Web Push（api/session-events.go）
	browser.InitConfig(cfg.DataDir) // Chrome 启动配置持久化到 dataDir
	phone.InitConfig(cfg.DataDir)   // 手机后端配置（本机模拟器/远程设备/真机）持久化到 dataDir
	hub := stream.New(tt, cfg.LogsDir)

	// 公开端点（登录 / 首次设置 / 版本 / 证书 / 导航页）——与中心 共用
	mountPublic(r, a, cfg)

	// 多机设置（设置页 › 多机）。**单机也挂**：用户就是从这一页把自己接到中心上的，
	// 没接之前它当然也得在。
	cl := &clusterAPI{cfgPath: cfg.ConfigPath, cluster: cfg.Cluster, client: cfg.NodeClient,
		bind: cfg.Bind, tls: cfg.TLSEnabled}

	// 受保护端点
	g := r.Group("/api", a.Middleware())
	// API 返回的都是动态数据（会话状态、文件内容/元信息…）。移动端(Safari/WebView)与反代会对
	// 无 Cache-Control 的 GET 做启发式缓存，导致文件实时重载轮询的 /file/stat 一直拿到旧 mtime
	// → 不刷新。统一禁缓存，兜底前端的 cache:no-store。
	g.Use(func(c *gin.Context) { c.Header("Cache-Control", "no-store") })
	{
		g.GET("/cluster/config", cl.Get) // 当前角色 + 接入状态 + 本机局域网地址
		g.PUT("/cluster/config", cl.Put) // 写回 config.yaml 的 cluster 段（令牌只写不读）
		g.POST("/cluster/restart", cl.Restart)

		g.GET("/me", h.Me)
		g.GET("/info", h.Info)

		g.GET("/fs", h.FS)
		g.GET("/files", h.Files)                // 文件侧栏：列目录
		g.GET("/file", h.File)                  // 文件侧栏：读文件
		g.POST("/file/save", h.FileSave)        // 文件侧栏：编辑器保存（覆盖写入既有文件）
		g.GET("/file/search", h.FileSearch)     // 文件侧栏：从当前目录递归按文件名搜索
		g.GET("/file/raw", h.FileRaw)           // 文件侧栏：原始字节（图片预览 / ?dl=1 下载）
		g.GET("/file/serve/*path", h.FileServe) // 文件侧栏：HTML 预览（绝对路径进 URL，令同目录相对引用可解析）
		g.GET("/file/preview", h.FilePreview)   // 文件侧栏：Office 转 PDF 预览
		g.GET("/file/stat", h.FileStat)
		g.GET("/file/download", h.FileDownload)

		// P2P 直连（M0a spike）：信令 WS + ICE 配置下发，均挂 g 组 cookie 自动鉴权。
		p2pHub := p2p.NewHub(p2p.HubConfig{
			Enabled:    cfg.P2PEnabled,
			ICEServers: cfg.P2PICEServers,
			UDPPort:    cfg.P2PUDPPort,
			UPnP:       cfg.P2PUPnP,
			MDNS:       cfg.P2PMDNS,
			DataDir:    cfg.DataDir,
		})
		// Phase 1b：浏览器镜像走 media PC 的 DataChannel（label 前缀 "screencast"）。
		// 在此接线避免 p2p↔browser 循环 import；WS 回退 /api/browser/stream 不受影响。
		p2p.RegisterScreencastHandler(browser.ScreencastDCHandler)
		// Phase 1b：手机镜像同法走 media PC 的 DataChannel（label 前缀 "phone"）。
		// 未接线/P2P 关时收到 phone 通道按「无 handler」关闭 → 前端回退 WS /api/phone/stream。
		p2p.RegisterPhoneHandler(phone.PhoneDCHandler)
		g.GET("/p2p/signal", p2pHub.SignalHandler)
		g.GET("/p2p/config", func(c *gin.Context) {
			// 一台一条，与后端 rtcConfiguration 同构（同一条里的 URL 共享凭据，见 p2p/ice.go）。
			servers := make([]gin.H, 0, len(cfg.P2PICEServers))
			for _, u := range cfg.P2PICEServers {
				servers = append(servers, gin.H{"urls": u})
			}
			c.JSON(http.StatusOK, gin.H{"iceServers": servers})
		})
		// M2 埋点接收端：前端一次传输结束（成功/回退）后上报 goodput 等指标。
		g.POST("/p2p/metric", p2pHub.MetricHandler)

		g.POST("/file/rename", h.FileRename)
		g.POST("/file/copy", h.FileCopy)
		g.POST("/file/move", h.FileMove) // 文件侧栏：移动文件/目录
		g.DELETE("/file", h.FileDelete)
		g.POST("/file/mkdir", h.FileMkdir) // 文件侧栏：在当前目录新建子目录
		g.POST("/file/touch", h.FileTouch) // 文件侧栏：在指定目录新建空文件
		g.POST("/upload", h.Upload)        // 上传文件到指定目录（拖拽到对话框 / 文件侧栏）

		g.GET("/git/status", h.GitStatus)    // Git 面板：当前工作目录所属仓库状态
		g.GET("/git/diff", h.GitDiff)        // Git 面板：单文件差异
		g.POST("/git/stage", h.GitStage)     // 暂存
		g.POST("/git/unstage", h.GitUnstage) // 取消暂存
		g.POST("/git/discard", h.GitDiscard) // 放弃改动
		g.POST("/git/commit", h.GitCommit)   // 提交（可选 push）
		g.POST("/git/op", h.GitOp)           // push / pull / fetch / sync
		g.GET("/git/is-repo", h.GitIsRepo)   // 检查是否 git 仓库
		g.GET("/git/graph", h.GitGraph)      // 提交树：DAG（parents + refs），泳道前端算
		g.GET("/git/refs", h.GitRefs)        // 分支页：本地/远端分支 + 标签 + 储藏
		g.GET("/git/show", h.GitShow)        // 单提交详情：元信息 + 文件清单
		g.POST("/git/action", h.GitAction)   // 本地引用操作：checkout/分支/合并/变基/reset/revert/stash
		// ── Worktree API（worktree.Service 独占 git 操作，设计 07 §4）──
		g.POST("/git/worktree", h.WorktreeCreate)        // 新建（锁内命名 + roam.* 身份）
		g.GET("/git/worktrees", h.WorktreeList)          // 清单 + 状态 + 会话 join（无写副作用）
		g.GET("/git/worktrees/all", h.WorktreeListAll)   // 跨仓库总览（会话触达的全部仓库）
		g.GET("/git/worktree/diff", h.WorktreeDiff)      // 对比 base（committed 与 workingTree 分开）
		g.POST("/git/worktree/merge", h.WorktreeMerge)   // 合并回 base（执行位/冲突 abort/expected-head）
		g.POST("/git/worktree/remove", h.WorktreeRemove) // 删除（占用检查 + 脏保护）
		g.POST("/git/worktree/prune", h.WorktreePrune)   // 显式清理残留
		g.POST("/git/worktree/finish", h.WorktreeFinish) // P3 孤儿收尾：冻结→wip→merge→remove→留痕
		g.POST("/git/worktree/sync", h.WorktreeSync)     // 远端轻量同步：ls-remote+fetch 合并目标，只动 refs/remotes（10 §3）
		g.GET("/git/branches", h.GitBranches)            // 本地分支列表（W1 start-from）
		g.GET("/git/pr", h.GitPR)                        // 这条分支在远端的 PR（gh CLI），分支状态弹层用
		// ── Session API 增量 ──
		g.GET("/sessions/annotations", h.SessionAnnotations)              // session→worktree 归属（cwd join）
		g.GET("/sessions/:name/worktree-status", h.SessionWorktreeStatus) // W7 关闭前预检
		// ── 组合 WorktreeSession API（事务编排）──
		g.POST("/worktree-sessions", h.WorktreeSessionCreate)                     // 建 worktree + 会话
		g.POST("/sessions/:name/fork", h.SessionFork)                             // 派生子会话（继承父 cwd）
		g.POST("/sessions/:name/fork-worktree", h.SessionForkWorktree)            // 派生子会话进新 worktree
		g.POST("/sessions/:name/close-with-worktree", h.SessionCloseWithWorktree) // W7 三选一
		// ── Race Service（W5/W6：一题多解竞赛，设计 07 §3）──
		g.POST("/races", h.RaceCreate)              // 开赛：逐选手 会话→worktree→发题
		g.GET("/races", h.RaceList)                 // 竞赛列表（业务数据模型）
		g.POST("/races/:id/crown", h.RaceCrown)     // 选为赢家：wip→merge→可选清理，阶段可续跑
		g.POST("/races/:id/cleanup", h.RaceCleanup) // 全部清理（会话+worktree+分支）
		g.DELETE("/races/:id", h.RaceDelete)        // 删除竞赛记录

		// ── 项目（08：项目=git 仓库，一等存储对象 + 读模型聚合）──
		g.GET("/projects", h.ProjectsList)                  // 列表聚合（发现通道读时收敛）
		g.POST("/projects", h.ProjectCreate)                // 显式创建（origin=user，不自动退场）
		g.DELETE("/projects/:key", h.ProjectDelete)         // 显式移除（纯台账，不动目录/会话）
		g.GET("/projects/:key/activity", h.ProjectActivity) // 活动流（全部分支近 30 天）
		g.PATCH("/projects/:key/prefs", h.ProjectPrefs)     // 置顶/显示名/默认 agent/base

		// ── 全局搜索（⌘K）：一个查询打项目/会话/项目文件三张表；全文另走一条 ──
		g.GET("/search", h.Search)
		g.GET("/search/content", h.SearchContent)

		g.GET("/sessions", h.Sessions)
		g.GET("/sessions/history", h.SessionHistory)        // 已结束的会话（M3）
		g.POST("/sessions/:name/restore", h.SessionRestore) // 按台账重开一个壳
		g.POST("/sessions", h.NewSession)
		g.PATCH("/sessions/:name", h.RenameSession)
		g.DELETE("/sessions/:name", h.KillSession)
		g.GET("/sessions/:name/capture", h.Capture)
		g.POST("/sessions/:name/keys", h.Keys)                       // 注入原始按键（响应 TUI 选择框）
		g.POST("/sessions/:name/type", h.SessionType)                // 字面量打字进 pane（终端页语音回填）
		g.GET("/sessions/:name/cwd", h.SessionCwd)                   // 会话工作目录（文件侧栏定位）
		g.GET("/sessions/:name/claude", h.ClaudeStatus)              // 检测是否在跑 claude
		g.GET("/sessions/:name/transcript", h.ClaudeTranscript)      // 读 claude 对话记录
		g.GET("/sessions/:name/codex", h.CodexStatus)                // 检测是否在跑 codex
		g.GET("/sessions/:name/codex-transcript", h.CodexTranscript) // 读 codex 对话记录
		g.GET("/sessions/:name/panes/active", h.ActivePane)          // 活动 pane 几何+cwd+前台进程（危险操作目标可视化）
		g.POST("/sessions/:name/panes/:paneId/close", h.ClosePane)   // 结构化关闭 pane（不走 confirm-before 按键路径）

		g.GET("/tasks", h.Tasks)
		g.POST("/tasks", h.Spawn)
		g.GET("/tasks/:g", h.TaskStatus)
		g.GET("/tasks/:g/collect", h.TaskCollect)
		g.DELETE("/tasks/:g", h.TaskKill)
		g.POST("/tasks/:g/send", h.Send)

		// 蜂群(swarm)：建群/加成员/管理 + 广场/看板
		g.GET("/swarm/subroles", h.SwarmSubroles)
		g.GET("/swarms", h.Swarms)
		g.POST("/swarms", h.SwarmNew)
		g.GET("/swarms/:n", h.SwarmStatus)
		g.DELETE("/swarms/:n", h.SwarmArchive)
		g.POST("/swarms/:n/adopt", h.SwarmAdopt)
		g.POST("/swarms/:n/members", h.SwarmAddMember)
		g.POST("/swarms/:n/done", h.SwarmDone)
		g.POST("/swarms/:n/activate", h.SwarmActivate)
		g.GET("/swarms/:n/feed", h.SwarmFeed)
		g.POST("/swarms/:n/say", h.SwarmSay)
		g.GET("/swarms/:n/board", h.SwarmBoard)
		g.POST("/swarms/:n/task", h.SwarmTaskAdd)
		g.PATCH("/swarms/:n/task/:id", h.SwarmTaskPatch)
		g.DELETE("/swarms/:n/task/:id", h.SwarmTaskDelete)

		// 插件:统一管理/配置(VS Code 式设置页;backend 只做 CLI 薄封装)
		g.GET("/plugins", h.Plugins)
		g.GET("/plugin/status", h.PluginStatus)
		g.POST("/plugin/daemon/start", h.PluginDaemonStart)
		g.POST("/plugin/track", h.PluginTrack)
		g.POST("/plugin/install", h.PluginInstall)
		g.GET("/plugin/removed", h.PluginsRemoved)
		g.DELETE("/plugins/:id", h.PluginUninstall)
		g.POST("/plugins/:id/restore", h.PluginRestore)
		g.GET("/plugin/findings", h.PluginFindings)
		g.GET("/plugin/notifications", h.PluginNotifications)
		g.GET("/inbox", h.InboxList)               // 收件箱：会话事件（等你 / 做完 / 出错）+ 角标
		g.POST("/inbox/read", h.InboxRead)         // 已读（ids 或 all）
		g.GET("/push/vapid", h.PushVAPID)          // 本部署的 VAPID 公钥
		g.POST("/push/subscribe", h.PushSubscribe) // 手机 PWA 的推送订阅
		g.DELETE("/push/subscribe", h.PushUnsubscribe)
		g.POST("/push/test", h.PushTest) // 发一条测试
		g.POST("/plugins/:id/enable", h.PluginSetEnabled(true))
		g.POST("/plugins/:id/disable", h.PluginSetEnabled(false))
		g.GET("/plugins/:id/config", h.PluginConfig)
		g.PUT("/plugins/:id/config", h.PluginConfigSet)
		g.GET("/plugins/:id/audit", h.PluginAudit)
		g.POST("/plugins/:id/run", h.PluginRun)

		g.GET("/football/players", h.FootballPlayers)
		g.POST("/football/players", h.FootballPlayerCreate)
		g.GET("/football/players/:id", h.FootballPlayer)
		g.PATCH("/football/players/:id", h.FootballPlayerPatch)
		g.DELETE("/football/players/:id", h.FootballPlayerDelete)
		g.GET("/football/teams", h.FootballTeams)
		g.POST("/football/teams", h.FootballTeamCreate)
		g.GET("/football/teams/:id", h.FootballTeam)
		g.PATCH("/football/teams/:id", h.FootballTeamPatch)
		g.DELETE("/football/teams/:id", h.FootballTeamDelete)
		g.PUT("/football/teams/:id/lineup", h.FootballTeamLineup)
		g.GET("/football/transfers", h.FootballTransfers)
		g.POST("/football/transfers", h.FootballTransferCreate)

		g.GET("/env", h.Env)
		g.PUT("/env", h.EnvSet)
		g.DELETE("/env/:key", h.EnvDelete)
		g.POST("/env/push", h.EnvPush)

		g.GET("/speech/config", h.GetSpeechConfig)       // 语音识别(ASR)服务商配置
		g.PUT("/speech/config", h.SetSpeechConfig)       //
		g.GET("/preferences", h.GetPreferences)          // 用户偏好（主题/语言/Agent 命令等）
		g.PUT("/preferences", h.SetPreferences)          //
		g.POST("/speech/transcribe", h.SpeechTranscribe) // 上传录音 → 返回识别文本

		g.POST("/password", a.ChangePassword) // 设置页改密（校验旧口令）→ /api/password

		g.GET("/2fa/qr", a.TOTPQR)            // 当前状态 + 密钥二维码
		g.GET("/2fa/gen", a.TOTPGen)          // 生成新密钥（开启前扫码用）
		g.POST("/2fa/enable", a.TOTPEnable)   // 确认动态码后开启
		g.POST("/2fa/disable", a.TOTPDisable) // 关闭

		// 实时通道
		g.GET("/term/:name", pty.Handler)
		g.GET("/browser/stream", browser.Handler) // 镜像全局 Chrome 画面
		g.GET("/browser/tabs", browser.Tabs)      // 标签页：列出
		g.POST("/browser/tabs", browser.NewTab)   // 标签页：新建
		g.DELETE("/browser/tabs/:id", browser.CloseTab)
		g.POST("/browser/tabs/:id/back", browser.TabBack)         // 后退
		g.POST("/browser/tabs/:id/forward", browser.TabForward)   // 前进
		g.POST("/browser/tabs/:id/reload", browser.TabReload)     // 刷新
		g.POST("/browser/tabs/:id/activate", browser.TabActivate) // 在 Chrome 里前置
		g.POST("/browser/tabs/:id/navigate", browser.TabNavigate) // 导航到 URL
		g.Any("/browser/cdp/*path", browser.DevToolsProxy)        // 反代 Chrome 自带 DevTools(F12) + CDP ws
		g.GET("/browser/config", browser.GetConfig)               // Chrome 启动配置：读
		g.PUT("/browser/config", browser.SetConfig)               // Chrome 启动配置：存
		g.POST("/browser/relaunch", browser.Relaunch)             // 按新配置重启 Chrome
		g.GET("/browser/health", browser.Health)                  // Chrome 是否可用 + 启动失败原因
		g.POST("/browser/open-external", browser.OpenExternal)    // 甩给宿主机真实浏览器打开（WSL 下唤起 Windows 浏览器）

		// 手机镜像（Linux→Android adb；其它平台 health 明示不支持）
		g.GET("/phone/stream", phone.Handler)                    // 镜像手机画面 + 转发输入
		g.GET("/phone/health", phone.Health)                     // 设备可用性 + 平台 + 目标
		g.GET("/phone/apps", phone.Apps)                         // 列出 App
		g.POST("/phone/apps/:id/launch", phone.Launch)           // 启动 App
		g.POST("/phone/key", phone.Key)                          // 系统键 back/home/enter...
		g.GET("/phone/ui", phone.UI)                             // 当前屏幕元素结构
		g.GET("/phone/config", phone.GetConfig)                  // 后端目标配置：读
		g.PUT("/phone/config", phone.SetConfig)                  // 后端目标配置：存（不自动连接）
		g.GET("/phone/status", phone.StatusInfo)                 // 单一状态源：依赖/运行/连接
		g.GET("/phone/devices", phone.Devices)                   // 可用目标设备列表(adb/idb)
		g.GET("/phone/platforms", phone.Platforms)               // 各平台安装/支持状态(开关)
		g.POST("/phone/install", phone.Install)                  // 按需(插件化)安装依赖
		g.POST("/phone/start", phone.Start)                      // 运行层：起设备(本机模拟器/iOS 模拟器)
		g.POST("/phone/stop", phone.Stop)                        // 运行层：停设备
		g.POST("/phone/connect", phone.Connect)                  // 连接层：adb connect(网络目标)
		g.POST("/phone/disconnect", phone.Disconnect)            // 连接层：adb disconnect
		g.POST("/phone/test", phone.Test)                        // 测试连接(Ensure+Health)
		g.POST("/phone/auto", phone.Auto)                        // 一键：装依赖→起设备→连接→测试
		g.GET("/phone/avd/catalog", phone.AVDCatalog)            // 新建向导：机型档 + 系统镜像目录
		g.POST("/phone/avd", phone.AVDCreate)                    // 新建模拟器(发号，后台跑)
		g.GET("/phone/avd/tasks/:id", phone.AVDTask)             // 新建进度(SSE)
		g.DELETE("/phone/avd/:name", phone.AVDDelete)            // 删除模拟器(连数据一起)
		g.POST("/phone/device/reconnect", phone.DeviceReconnect) // USB 真机：救回未授权/离线
		g.POST("/phone/device/wireless", phone.DeviceWireless)   // USB 真机：转无线调试，之后可拔线

		g.GET("/stream/status", hub.Status)
		g.GET("/logs/:name", hub.Logs)
	}

	mountWeb(r, cfg.FrontendDir)
	return r
}

func fileExists(p string) bool {
	if p == "" {
		return false
	}
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

const roamRepo = "ybz21/Roam"

var (
	ucMu   sync.Mutex
	ucAt   time.Time
	ucData gin.H
)

// checkUpdate 查 GitHub 最新 release（含 prerelease），与当前版本比对。
// 成功结果缓存 30 分钟；失败也返回 releases 页地址，前端据此优雅降级（仍可手动前往）。
func checkUpdate(current string) gin.H {
	releases := "https://github.com/" + roamRepo + "/releases"
	ucMu.Lock()
	defer ucMu.Unlock()
	if ucData != nil && time.Since(ucAt) < 30*time.Minute {
		return ucData
	}
	res := gin.H{"current": current, "repo": roamRepo, "releases": releases}
	client := &http.Client{Timeout: 6 * time.Second}
	req, _ := http.NewRequest("GET", "https://api.github.com/repos/"+roamRepo+"/releases?per_page=1", nil)
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := client.Do(req)
	if err != nil {
		res["error"] = "unreachable"                        // 网络不通/被墙/超时
		ucData, ucAt = res, time.Now().Add(-25*time.Minute) // 只缓存 5 分钟，尽快重试
		return res
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		res["error"] = "http_" + strconv.Itoa(resp.StatusCode) // 常见 403 限流
		ucData, ucAt = res, time.Now().Add(-25*time.Minute)
		return res
	}
	var arr []struct {
		Tag  string `json:"tag_name"`
		URL  string `json:"html_url"`
		Pre  bool   `json:"prerelease"`
		Name string `json:"name"`
	}
	if json.NewDecoder(resp.Body).Decode(&arr) == nil && len(arr) > 0 {
		res["latest"] = arr[0].Tag
		res["url"] = firstNonEmptyStr(arr[0].URL, releases)
		res["prerelease"] = arr[0].Pre
		res["newer"] = isNewer(arr[0].Tag, current)
	}
	ucData, ucAt = res, time.Now()
	return res
}

// isNewer 判断 latest 是否比 current 新：current 为空/dev 一律视为可更新；
// 否则按去掉前导 v 的字符串是否不同（保守：不同即提示，交由用户到 release 页确认）。
func isNewer(latest, current string) bool {
	c := strings.TrimPrefix(strings.TrimSpace(current), "v")
	if c == "" || c == "dev" {
		return true
	}
	return strings.TrimPrefix(strings.TrimSpace(latest), "v") != c
}

func firstNonEmptyStr(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

// mountPublic 注册免登录的公开端点（登录 / 首次设置 / 版本 / 检测更新 / 下载证书 /
// 导航起始页）。单机（New）与中心（NewHub）共用同一套入口。
func mountPublic(r *gin.Engine, a *auth.Auth, cfg Config) {
	r.POST("/api/login", a.Login)
	r.POST("/api/logout", a.Logout)
	r.POST("/api/setup", a.Setup)                // 首次设置口令（仅当尚未设置口令时可用），成功即发会话
	r.GET("/api/pubconfig", a.PubConfig)         // 登录页据此决定是否要动态码 / 是否需首次设置
	r.GET("/api/version", func(c *gin.Context) { // roam 版本 + 仓库（关于页/检测更新，免登录）
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"version": cfg.Version, "repo": roamRepo}})
	})
	// 检测更新：后端查 GitHub Releases（带缓存 + 优雅降级），避免浏览器直连 GitHub API
	// 遇到的限流/跨域/网络不通问题。无论成功与否都返回 releases 页地址供手动前往。
	r.GET("/api/update-check", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"data": checkUpdate(cfg.Version)})
	})

	// 下载自签证书（免登录）：手机装为受信任证书后即把本站当安全上下文，
	// 可装成全屏 PWA、麦克风/剪贴板可用。TLS 关闭或证书不存在时返回 404。
	r.GET("/cert.crt", func(c *gin.Context) {
		if cfg.TLSCertPath == "" {
			c.String(404, "TLS 未启用，无证书可下载")
			return
		}
		pem, err := os.ReadFile(cfg.TLSCertPath)
		if err != nil {
			c.String(404, "证书不存在")
			return
		}
		// application/x-x509-ca-cert：安卓据此弹出「安装 CA 证书」流程。
		c.Header("Content-Type", "application/x-x509-ca-cert")
		c.Header("Content-Disposition", `attachment; filename="ttmux-ca.crt"`)
		c.Data(200, "application/x-x509-ca-cert", pem)
	})

	// 导航起始页（免登录）：供被投屏的 Chrome 当默认主页，因此不能挂在认证组里
	hm := home.New(cfg.DataDir)
	r.GET("/home", hm.Page)
	r.GET("/home/sites", hm.GetSites)
	r.PUT("/home/sites", hm.PutSites)
}

func mountWeb(r *gin.Engine, frontendDir string) {
	indexPath := filepath.Join(frontendDir, "index.html")
	useReact := fileExists(indexPath)

	if useReact {
		assetsDir := filepath.Join(frontendDir, "assets")
		serveAsset := func(c *gin.Context) {
			fp := filepath.Join(assetsDir, filepath.Clean("/"+c.Param("filepath")))
			if !strings.HasPrefix(fp, assetsDir) || !fileExists(fp) {
				c.Status(http.StatusNotFound)
				return
			}
			// 产物文件名带内容 hash（内容变则名变），可放心让浏览器缓存一年且免回源验证；
			// 否则每次打开页面都对全部 JS/CSS 发条件请求甚至重新下载，首屏明显变慢。
			c.Header("Cache-Control", "public, max-age=31536000, immutable")
			c.Header("Vary", "Accept-Encoding")
			// 构建期预压缩的 .br/.gz 旁路文件（见 frontend/scripts/compress-dist.mjs）：
			// 按 Accept-Encoding 择优直接下发（br 比 gzip 再小 15~20%，浏览器仅 HTTPS 下声明支持），
			// 几 MB 的 JS 传输量降到约 1/4~1/3。
			ae := c.GetHeader("Accept-Encoding")
			for _, enc := range [...]struct{ name, ext string }{{"br", ".br"}, {"gzip", ".gz"}} {
				if !strings.Contains(ae, enc.name) || !fileExists(fp+enc.ext) {
					continue
				}
				ct := mime.TypeByExtension(filepath.Ext(fp))
				if ct == "" {
					ct = "application/octet-stream"
				}
				c.Header("Content-Type", ct)
				c.Header("Content-Encoding", enc.name)
				c.File(fp + enc.ext)
				return
			}
			c.File(fp)
		}
		r.GET("/assets/*filepath", serveAsset)
		r.HEAD("/assets/*filepath", serveAsset)
		log.Printf("前端: React (磁盘 %s)", frontendDir)
	} else {
		log.Printf("前端: 内嵌回退页 —— 运行 ./start.sh --dev 会构建 React")
	}

	serve := func(c *gin.Context) {
		c.Header("Cache-Control", "no-cache, no-store, must-revalidate")
		if useReact {
			c.File(indexPath)
			return
		}
		c.Data(http.StatusOK, "text/html; charset=utf-8", fallbackHTML)
	}
	r.GET("/", serve)
	r.NoRoute(func(c *gin.Context) {
		p := c.Request.URL.Path
		if strings.HasPrefix(p, "/api") {
			c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "NOT_FOUND"}})
			return
		}
		// public 下的静态文件（logo、favicon、manifest 等）：存在就直接返回
		if useReact && p != "/" {
			fp := filepath.Join(frontendDir, filepath.Clean("/"+p))
			if strings.HasPrefix(fp, frontendDir) && fileExists(fp) {
				c.File(fp)
				return
			}
		}
		serve(c) // 否则按 SPA history 路由回退到 index.html
	})
}
