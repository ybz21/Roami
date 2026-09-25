// roami-web — Roami 的 Web 控制台后端入口。
// 读取 ~/.roami/config.yaml（缺失则由内嵌模板生成）→ 叠加 flag → 组装 server.Config → 启动 Gin。
package main

import (
	"context"
	"flag"
	"log"
	"net"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"

	"github.com/gin-gonic/gin"
	"ttmux-web/browser"
	"ttmux-web/cluster/node"
	"ttmux-web/config"
	"ttmux-web/internal/clibin"
	"ttmux-web/internal/webui"
	"ttmux-web/server"
	"ttmux-web/ttmux"
)

// version 是 roam 版本号，发布时由 -ldflags "-X main.version=<tag>" 注入（默认 dev）。
var version = "dev"

func main() {
	// 子命令层（roam im send / roam cron list / roam ttmux ls…）。
	// 必须在 flag.Parse 之前：flag 包遇到非 flag 参数就停下，之后的 --text 会被当成
	// 本进程的 flag 报错。不带子命令（或第一个参数是 -flag）时原样往下走，启动服务。
	config.BridgeEnvAliases() // ROAMI_* 与 ROAM_* 互为别名（改名前写好的脚本继续有效）
	if handled, code := runCLI(os.Args[1:], envOr("TTMUX_BIN", "ttmux")); handled {
		os.Exit(code)
	}

	configFlag := flag.String("config", "", "配置文件路径（覆盖 ROAMI_CONFIG / ~/.roami/config.yaml）")
	addrFlag := flag.String("addr", "", "监听地址，如 0.0.0.0:13579（覆盖配置里的 web.bind）")
	webFlag := flag.String("web", "", "前端构建产物目录 frontend/dist（覆盖自动探测；留空用内嵌前端）")
	tlsFlag := flag.Bool("tls", false, "强制启用自签 HTTPS（覆盖配置里的 web.tls=false）")
	tlsCertFlag := flag.String("tls-cert", "", "TLS 证书路径（缺省 <home>/tls/cert.pem，缺失则自动生成）")
	tlsKeyFlag := flag.String("tls-key", "", "TLS 私钥路径（缺省 <home>/tls/key.pem，缺失则自动生成）")
	flag.Parse()

	// 迁移旧数据目录（~/.roam、~/.ttmux、~/.local/share/ttmux → ~/.roami），随后加载配置。
	migrateLegacyHome()
	cfgPath := *configFlag
	if cfgPath == "" {
		cfgPath = config.ResolvePath()
	}
	conf, err := config.Load(cfgPath)
	if err != nil {
		log.Fatalf("读取配置失败(%s): %v", cfgPath, err)
	}

	bin := envOr("TTMUX_BIN", "ttmux")
	bind := firstNonEmpty(*addrFlag, conf.Web.Bind)
	// 前端目录：显式 -web > 磁盘探测（开发）> 内嵌产物解压（单一二进制发行）。
	fdir := *webFlag
	if fdir == "" {
		fdir = frontendDir()
	}
	if fdir == "" {
		fdir = webui.Ensure(dataDir())
	}

	// 登录口令来自配置（明文）。为空表示未设置 → 前端进入首次设置流程，此处不再随机生成。
	pw := conf.Web.Password
	if pw == "" {
		log.Printf("⚠ 未设置登录口令，请首次打开网页时在界面上设置（也可编辑 %s 的 web.password）", cfgPath)
	}
	// 中心 不跑业务，自然也用不着 ttmux——不要为它解压内嵌副本，更不要报缺失。
	if _, err := exec.LookPath(bin); err != nil && conf.Cluster.Mode != "hub" {
		// PATH 上没有 ttmux：单一二进制发行时用内嵌的 ttmux（解压到 <home>/bin）。
		if p := clibin.Ensure(dataDir()); p != "" {
			bin = p
			_ = os.Setenv("TTMUX_BIN", p) // 让 roam 拉起的 ttmux 子进程也用它
			log.Printf("已启用内嵌 ttmux: %s", p)
		} else {
			log.Printf("⚠ 找不到 ttmux (%s)，请确认已安装并在 PATH 中", bin)
		}
	}

	// 两步验证：初始种子来自配置 web.totp_secret（two_fa=off 可临时关闭）；
	// 之后可在控制台「系统配置」里开启/关闭，状态持久化到 totp.json（以文件为准）。
	totp := conf.ResolvedTOTPSecret()

	// TLS：配置 web.tls 或 -tls 真值开启。证书缺失则就地生成自签证书（SAN 覆盖本机 IP + 配置的 tls_san）。
	tlsOn := conf.Web.TLS || *tlsFlag
	certPath := firstNonEmpty(*tlsCertFlag, envOr("ROAM_WEB_TLS_CERT", envOr("TTMUX_WEB_TLS_CERT", "")), filepath.Join(dataDir(), "tls", "cert.pem"))
	keyPath := firstNonEmpty(*tlsKeyFlag, envOr("ROAM_WEB_TLS_KEY", envOr("TTMUX_WEB_TLS_KEY", "")), filepath.Join(dataDir(), "tls", "key.pem"))
	// 「下载证书」端点下发的是根 CA（手机装它），而非服务器叶子证书。
	caCertPath := filepath.Join(filepath.Dir(certPath), "ca-cert.pem")
	scheme := "http"
	if tlsOn {
		scheme = "https"
	}

	// 导航起始页挂在本服务的公开路由 /home 上（免登录，供被投屏的 Chrome 当默认主页）。
	// Chrome 与本服务同机，统一用回环地址访问（绑定即便是 0.0.0.0 也走 127.0.0.1）。
	port := "13579"
	if _, p, err := net.SplitHostPort(bind); err == nil && p != "" {
		port = p
	}
	homeURL := scheme + "://127.0.0.1:" + port + "/home"

	cfg := server.Config{
		TTmuxBin:    bin,
		EmbeddedBin: embeddedBin(),
		LogsDir:     logsDir(),
		FrontendDir: fdir,
		BrowserHome: homeURL,
		DataDir:     dataDir(),
		TLSCertPath: tlsCertPathIf(tlsOn, caCertPath),
		Password:    pw,
		TOTPSecret:  totp,
		TOTPState:   filepath.Join(dataDir(), "totp.json"),
		LockAfter:   conf.Web.LockAfter,
		LockSecs:    conf.Web.LockSecs,
		SavePassword: func(newPW string) error {
			return config.SavePassword(cfgPath, newPW)
		},
		Version:       version,
		P2PEnabled:    conf.Web.P2PEnabled,
		P2PICEServers: conf.Web.P2PICEServers,
		P2PUDPPort:    conf.Web.P2PUDPPort,
		P2PUPnP:       conf.Web.P2PUPnP,
		P2PMDNS:       conf.Web.P2PMDNS,
		ConfigPath:    cfgPath,
		Cluster:       conf.Cluster,
		Bind:          bind,
		TLSEnabled:    tlsOn,
	}

	// 诊断口：默认不开，ROAM_PPROF=127.0.0.1:6060 才起（只绑回环，见 pprof.go）
	if a := os.Getenv("ROAM_PPROF"); a != "" {
		startPprof(a)
	}

	// 横向扩展模式分流（见 docs/design/cluster/architecture.html §1/§3）：
	//   - cloud：中心，只做路由 + 注册表 + 控制台，不构造业务 runtime；
	//   - standard（默认）：现在的单机 Roami；若配了 cluster.broker，则额外出站注册进云端。
	// standard 下**本机监听口照常对外**——上云和局域网直连是两条并行的入口，不是二选一。
	var r *gin.Engine
	if conf.Cluster.Mode == "hub" {
		log.Printf("以「中心」模式启动（只做入口 + 机器注册表 + 控制台，不跑本机业务）")
		r = server.NewHub(cfg)
	} else {
		// 隧道客户端先建出来（哪怕不启动）：设置页要靠它报接入状态。
		var cl *node.Client
		if conf.Cluster.Hub != "" {
			cl = &node.Client{
				Hub:      conf.Cluster.Hub,
				Token:    conf.Cluster.Token,
				Name:     conf.Cluster.Name,
				Group:    conf.Cluster.Group,
				Insecure: conf.Cluster.Insecure,
				Version:  version,
				CredPath: filepath.Join(dataDir(), "cluster", "node.json"),
				Stats:    nodeStats(bin),
			}
		}
		cfg.NodeClient = cl
		r = server.New(cfg)
		if cl != nil {
			cl.Handler = r // 业务 Handler 不变，隧道请求经内部主体放行本地鉴权
			go cl.Run(context.Background())
			log.Printf("这台机器：出站接入中心 %s（局域网直连口 %s 照常可用）", conf.Cluster.Hub, bind)
		}
	}

	// 退出时回收本进程拉起的 Chrome（含其子进程组），避免泄漏孤儿进程
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sig
		browser.Shutdown()
		os.Exit(0)
	}()

	if tlsOn {
		gen, err := ensureSelfSignedCert(certPath, keyPath, conf.Web.TLSSAN)
		if err != nil {
			log.Fatalf("生成/读取自签 TLS 证书失败: %v", err)
		}
		if gen {
			log.Printf("已生成自签 TLS 证书: %s", certPath)
		}
		log.Printf("ttmux-web 监听 https://%s  (ttmux=%s；自签证书：桌面/安卓首访点「继续前往」即可，iPhone 要收推送须先装 /cert.crt 并信任；明文 http 会自动跳转)", bind, bin)
		// 不用 r.RunTLS：它只认 TLS 握手，地址栏少打个 s 就是一句
		// "Client sent an HTTP request to an HTTPS server."（HTTP 400），
		// 用户看不出该怎么办。见 tlsredirect.go。
		if err := serveTLSWithRedirect(r, bind, certPath, keyPath); err != nil {
			log.Fatal(err)
		}
		return
	}
	log.Printf("ttmux-web 监听 http://%s  (ttmux=%s)", bind, bin)
	if err := r.Run(bind); err != nil {
		log.Fatal(err)
	}
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func firstNonEmpty(vals ...string) string {
	for _, v := range vals {
		if v != "" {
			return v
		}
	}
	return ""
}

// tlsCertPathIf 仅在 TLS 开启时返回证书路径，供「下载证书」端点下发；关闭时返回空（端点 404）。
func tlsCertPathIf(on bool, path string) string {
	if on {
		return path
	}
	return ""
}

// dataDir 返回后端数据目录（TLS 证书、totp.json 等）。默认 Roami 主目录 ~/.roami；
// 可用 ROAM_DATA 覆盖（兼容旧 TTMUX_DATA）。
// embeddedBin 解出内嵌的 ttmux 路径（dev 构建里内嵌的是占位符，返回空）。
func embeddedBin() string {
	if !clibin.Embedded() {
		return ""
	}
	return clibin.Ensure(dataDir())
}

func dataDir() string {
	if data := envOr("ROAMI_DATA", envOr("ROAM_DATA", os.Getenv("TTMUX_DATA"))); data != "" {
		return data
	}
	return config.Home()
}

func logsDir() string { return filepath.Join(dataDir(), "logs") }

// migrateLegacyHome 首次启动时把旧目录迁移到 ~/.roami：
//   - ~/.roam → ~/.roami（改名 Roami 之前的主目录）
//   - ~/.ttmux → ~/.roami（更早那次改名之前的）
//   - ~/.local/share/ttmux 里的 tls/、totp.json → ~/.roami（旧后端数据目录）
//
// 仅在目标不存在时迁移，且尊重自定义路径（ROAMI_/ROAM_ 的 HOME/DATA）（此时不动）。
// 整体 rename：数据一个字节都不动，Linux 上已打开的 fd 跟着 inode 走，
// 正在跑的 plugind 不会因为这次改名断掉。
func migrateLegacyHome() {
	for _, k := range []string{"ROAMI_HOME", "ROAM_HOME", "TTMUX_HOME"} {
		if os.Getenv(k) != "" {
			return
		}
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return
	}
	roam := filepath.Join(home, ".roami")
	if _, err := os.Stat(roam); err == nil {
		return // 已存在，视为已迁移
	}
	for _, legacyHome := range []string{filepath.Join(home, ".roam"), filepath.Join(home, ".ttmux")} {
		st, err := os.Stat(legacyHome)
		if err != nil || !st.IsDir() {
			continue
		}
		if err := os.Rename(legacyHome, roam); err != nil {
			log.Printf("⚠ 迁移 %s → %s 失败: %v", legacyHome, roam, err)
			return
		}
		log.Printf("已迁移旧目录 %s → %s", legacyHome, roam)
		break
	}
	// 旧运行时数据目录 ~/.local/share/ttmux/*（tls/totp.json/logs/groups/meta/env/agents…）
	// 并入 ~/.roami（不覆盖已存在的目标）。
	legacyData := filepath.Join(home, ".local", "share", "ttmux")
	entries, err := os.ReadDir(legacyData)
	if err != nil {
		return
	}
	_ = os.MkdirAll(roam, 0o700)
	for _, e := range entries {
		dst := filepath.Join(roam, e.Name())
		if _, err := os.Stat(dst); err == nil {
			continue // 目标已存在，不覆盖
		}
		_ = os.Rename(filepath.Join(legacyData, e.Name()), dst)
	}
}

// frontendDir 解析前端构建产物目录（仓库根 frontend/dist，与后端分离）。
// 优先 TTMUX_WEB_FRONTEND；否则在可执行文件与工作目录附近探测。
func frontendDir() string {
	if d := os.Getenv("TTMUX_WEB_FRONTEND"); d != "" {
		return d
	}
	candidates := []string{}
	if exe, err := os.Executable(); err == nil {
		base := filepath.Dir(exe)
		candidates = append(candidates,
			filepath.Join(base, "..", "frontend", "dist"), // backend/ 下的二进制 → ../frontend/dist
			filepath.Join(base, "frontend", "dist"),
		)
	}
	if cwd, err := os.Getwd(); err == nil {
		candidates = append(candidates,
			filepath.Join(cwd, "frontend", "dist"),
			filepath.Join(cwd, "..", "frontend", "dist"),
		)
	}
	for _, d := range candidates {
		if st, err := os.Stat(filepath.Join(d, "index.html")); err == nil && !st.IsDir() {
			return d
		}
	}
	return ""
}

// nodeStats 给心跳提供「这台机器上有几个会话、负载多少」。会话数走 tmux，负载读
// /proc/loadavg（非 Linux 读不到就报 0，不值得为它引一个跨平台依赖）。
func nodeStats(bin string) func() (int, float64) {
	tt := ttmux.New(bin)
	return func() (int, float64) {
		n := 0
		if out, err := tt.Run("list-sessions", "-F", "#{session_name}"); err == nil {
			for _, line := range strings.Split(strings.TrimSpace(out), "\n") {
				if strings.TrimSpace(line) != "" {
					n++
				}
			}
		}
		load := 0.0
		if b, err := os.ReadFile("/proc/loadavg"); err == nil {
			if f, err := strconv.ParseFloat(strings.Fields(string(b))[0], 64); err == nil {
				load = f
			}
		}
		return n, load
	}
}
