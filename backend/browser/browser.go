// Package browser 把一台全局 Chrome 的可视画面镜像到浏览器端。
//
// 不引入额外依赖：Chrome DevTools 协议(CDP)本身就是 WebSocket JSON-RPC，
// 直接用项目已有的 gorilla/websocket 桥接即可。
//
// 单实例模型：全局只对接一台 Chrome（调试端口默认 127.0.0.1:9222）。
//   - 若该端口已有 Chrome（比如 agent 自己起的），直接附着，不重复拉起；
//   - 若没有，本进程拉起一个带远程调试端口的 Chrome。
package browser

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/browsertabs"
)

// CDPBase 是 Chrome 远程调试根地址。默认 127.0.0.1:9222；端口被占时会自动换一个空闲端口并记录复用。
// 设了环境变量 TTMUX_CHROME_CDP 则固定用它（不自动换端口）。
var (
	cdpMu    sync.RWMutex
	cdpFixed = os.Getenv("TTMUX_CHROME_CDP") != ""
	CDPBase  = envOr("TTMUX_CHROME_CDP", "http://127.0.0.1:9222")
)

// 仅登记「本进程亲手拉起」的 Chrome，用于退出时回收；附着到已存在的 Chrome 时为 nil，不回收。
var (
	procMu sync.Mutex
	chrome *exec.Cmd

	launchMu   sync.Mutex // 串行化拉起，避免并发/轮询同时各拉一个
	lastLaunch time.Time  // 上次拉起时刻，做冷却防抖（端口没起来时别每次轮询都重开）

	statusMu sync.Mutex // 保护 lastErr
	lastErr  string     // 最近一次 ensureChrome 失败原因，供 /browser/health 回显到 UI
)

func setLastErr(s string) { statusMu.Lock(); lastErr = s; statusMu.Unlock() }

// cdpHTTP 专用于 CDP 的 HTTP 端点（/json*）。必须带超时：默认 http.Get 没有超时，端口上要是
// 蹲了个「只监听不回话」的进程（占了 9222 的非 Chrome 程序），探活就永久挂住——alive() 在
// /browser/tabs 轮询和 ensureChrome 的等待循环里都调，一挂就是整条请求链卡死。
var cdpHTTP = &http.Client{Timeout: 3 * time.Second}

func cdpAddress() string { cdpMu.RLock(); defer cdpMu.RUnlock(); return CDPBase }

func setCDPAddress(address string) { cdpMu.Lock(); CDPBase = address; cdpMu.Unlock() }

// cdpPort 解析 CDPBase 里的端口；解析失败回落 9222。
func cdpPort() int {
	if u, err := url.Parse(cdpAddress()); err == nil {
		if _, p, err := net.SplitHostPort(u.Host); err == nil {
			if n, err := strconv.Atoi(p); err == nil {
				return n
			}
		}
	}
	return 9222
}

// setCDPPort 切到新端口并持久化记录（下次启动优先复用，避免反复换端口开多个 Chrome）。
func setCDPPort(port int) {
	setCDPAddress(fmt.Sprintf("http://127.0.0.1:%d", port))
	recordPort(port)
}

// portFree 探测某端口当前是否可监听（被占则 false）。
func portFree(port int) bool {
	ln, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)))
	if err != nil {
		return false
	}
	_ = ln.Close()
	return true
}

// pickFreePort 让内核分配一个空闲端口。
func pickFreePort() (int, bool) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return 0, false
	}
	defer ln.Close()
	return ln.Addr().(*net.TCPAddr).Port, true
}

func envOr(k, d string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return d
}

func chromeExecutable() string {
	if v := os.Getenv("CHROME_BIN"); v != "" {
		if _, err := os.Stat(v); err == nil {
			return v
		}
	}
	for _, name := range []string{"google-chrome", "chromium", "chromium-browser"} {
		if p, err := exec.LookPath(name); err == nil {
			return p
		}
	}
	for _, p := range []string{
		"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
		"/Applications/Chromium.app/Contents/MacOS/Chromium",
	} {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return "google-chrome"
}

type target struct {
	ID                   string `json:"id"`
	Type                 string `json:"type"`
	Title                string `json:"title"`
	URL                  string `json:"url"`
	WebSocketDebuggerURL string `json:"webSocketDebuggerUrl"`
}

// ensureChrome 确保调试端口可用；不可用则尝试拉起一个 Chrome。
// 关键：串行 + 冷却 + 不重复拉起。否则在 macOS 上若拉起的 Chrome 没能在 9222 就绪，
// 每次 /browser/tabs 轮询(3s)都会再拉一个；而同 user-data-dir 的 Chrome 是单例，
// 第二个会把 about:blank 转发给已有实例后退出 → 表现为「不停弹 about:blank 窗口」。
func ensureChrome() error {
	if alive() {
		return nil
	}
	launchMu.Lock()
	defer launchMu.Unlock()
	return ensureChromeLocked()
}

func ensureChromeLocked() error {
	if !localCDP() {
		return fmt.Errorf("remote Chrome must be restarted on its host")
	}
	if alive() { // 双检：等锁期间别的协程可能已拉起就绪
		return nil
	}
	// 已有本进程拉起的 Chrome 仍在运行，或刚拉起过(冷却内)：不再开新的，给端口一点时间起来。
	procMu.Lock()
	running := chrome != nil && chrome.Process != nil
	procMu.Unlock()
	if running || time.Since(lastLaunch) < 12*time.Second {
		// 按总时限等而不是按次数：探活自身可能要等满超时（端口被「只监听不回话」的进程占着），
		// 按次数写就是 30 × 超时，把整条 HTTP 请求拖成分钟级。
		for deadline := time.Now().Add(3 * time.Second); time.Now().Before(deadline); {
			if alive() {
				return nil
			}
			time.Sleep(100 * time.Millisecond)
		}
		err := fmt.Errorf("Chrome 启动中或上次未就绪，调试端口 %s 暂未就绪", cdpAddress())
		setLastErr(err.Error())
		return err
	}

	cfg := effectiveConfig() // Settings 里存的值 > env > 默认

	// 单实例优先：同 profile 的 Chrome 已经在跑，只是调试端口不是我们记着的那个 → 附着它。
	// 同 user-data-dir 的 Chrome 是单例，这时候再拉一个只会把命令行转交给它然后自己退出，
	// 端口永远不开；与其报「启动后随即退出」，不如认下这台（chrome CLI 读同一份端口记录，
	// 跟着一起走）。固定端口模式是用户显式钉死的地址，不替他改。
	if !cdpFixed {
		if p := profileInstancePort(cfg.Profile); p > 0 && p != cdpPort() && aliveAt(p) {
			setCDPPort(p)
			setLastErr("")
			return nil
		}
	}
	if currentChromePID() > 0 {
		return fmt.Errorf("Chrome is not responding; waiting for recovery or a manual restart")
	}

	// 端口选择：当前端口被别的进程占着（且不是可用 Chrome，否则上面 alive 已 attach）→ 换一个空闲端口，
	// 并记录复用，避免反复换端口开出多个 Chrome。固定端口模式(TTMUX_CHROME_CDP)不自动换。
	port := cdpPort()
	if !cdpFixed && !portFree(port) {
		if p, ok := pickFreePort(); ok {
			port = p
			setCDPPort(port)
		}
	}

	args := []string{
		"--remote-debugging-port=" + strconv.Itoa(port),
		"--remote-debugging-address=127.0.0.1",
		"--remote-allow-origins=*",
		// profile 目录：默认隔离的临时 profile（不带你真实 Chrome 的登录/cookie/扩展）。
		// 想复用真实登录态：把 profile 指到真实目录，但需先完全退出你平时的 Chrome（同 profile
		// 不能两实例同时占用），且 Google 登录可能被「浏览器不安全」拦。
		"--user-data-dir=" + cfg.Profile,
		"--no-first-run", "--no-default-browser-check",
		// 高 DPI 渲染：像素密度翻倍但 CSS 布局不变 → 画面更清晰
		"--force-device-scale-factor=" + cfg.Scale,
		// 隐藏 navigator.webdriver 等自动化痕迹：镜像 Chrome 由 CDP 驱动，天然带自动化特征，
		// 部分站点（尤其搜索引擎）据此提高验证码触发概率；关掉这个 blink 特性降低误伤。
		"--disable-blink-features=AutomationControlled",
	}
	// 无头/有头：auto=按有无显示器自动判断；on=强制无头；off=强制有头。
	// 强制有头但无显示器(DISPLAY 空)时 Chrome 会起不来——属用户显式选择。
	// WSL 下 WSLg 会自带一个 DISPLAY，但那不是「有真实显示器」——有头模式会被 WSLg 转发成
	// 一个糊在 Windows 桌面上的杂散 Linux 窗口，而非「浏览器镜像」想要的服务端截屏。
	// 所以 WSL 下即便 DISPLAY 非空也按无头处理，除非用户显式选了「off」。
	headless := cfg.Headless == "on" ||
		(cfg.Headless != "off" && runtime.GOOS != "darwin" && (isWSL() || os.Getenv("DISPLAY") == ""))
	if headless { // screencast 在无头下同样可用
		args = append(args, "--headless=new", "--window-size="+cfg.WindowSize)
		if runtime.GOOS == "linux" && cfg.Profile == "/tmp/ttmux-chrome" {
			// The default isolated profile must not wait for an invisible desktop keyring prompt.
			args = append(args, "--password-store=basic")
		}
	} else if cfg.Fullscreen != nil && *cfg.Fullscreen { // 有头：全屏启动，画面铺满宿主屏幕
		args = append(args, "--start-fullscreen")
	}
	args = append(args, "about:blank")
	exe := cfg.Bin
	if exe == "" {
		exe = chromeExecutable()
	}
	cmd := exec.Command(exe, args...)
	// 不继承本进程的 stdout/stderr：避免 Chrome 日志刷屏，也避免持有管道导致父进程读阻塞
	cmd.Stdout = nil
	cmd.Stderr = nil
	// 自成进程组：回收时可整组 kill（含 zygote/gpu/renderer/crashpad 等子进程）
	cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if err := cmd.Start(); err != nil {
		e := fmt.Errorf("拉起 Chrome 失败(可执行路径 %s): %w", exe, err)
		setLastErr(e.Error())
		return e
	}
	lastLaunch = time.Now()
	procMu.Lock()
	chrome = cmd
	procMu.Unlock()
	// 收尸 + 退出即清空 chrome：让「chrome != nil」可靠表示「我们拉起的实例仍在运行」，
	// 进程退出后不再被误判为「还在跑」而长期不重拉。
	go func() {
		_ = cmd.Wait()
		procMu.Lock()
		if chrome == cmd {
			chrome = nil
		}
		procMu.Unlock()
	}()
	for deadline := time.Now().Add(5 * time.Second); time.Now().Before(deadline); { // 最多等 5s（含探活自身耗时）
		if alive() {
			setLastErr("") // 就绪：清掉上次错误
			if *cfg.AutoRecover && !restarting.Load() {
				if _, err := restoreTabs(savedRecoveryURLs(), savedRecoveryTabs()); err != nil {
					return err
				}
			}
			return nil
		}
		time.Sleep(100 * time.Millisecond)
	}
	// 没就绪：区分「进程已退出」(多半 profile 被占/参数不支持/可执行有问题) 与「还在慢启动」
	procMu.Lock()
	exited := chrome == nil
	procMu.Unlock()
	var e error
	if exited {
		e = fmt.Errorf("Chrome 启动后随即退出（常见：profile %q 被你平时的 Chrome 占用，或可执行路径/参数有误）", cfg.Profile)
	} else {
		e = fmt.Errorf("Chrome 调试端口 %s 未就绪（启动较慢或端口被防火墙拦）", cdpAddress())
	}
	setLastErr(e.Error())
	return e
}

// Shutdown 回收本进程拉起的 Chrome（整进程组）。附着到外部 Chrome 时为空操作。
// 由 main 在收到 SIGINT/SIGTERM 时调用。
func Shutdown() {
	procMu.Lock()
	defer procMu.Unlock()
	if chrome == nil || chrome.Process == nil {
		return
	}
	if pgid, err := syscall.Getpgid(chrome.Process.Pid); err == nil {
		_ = syscall.Kill(-pgid, syscall.SIGKILL) // 负 pgid = 杀整组
	} else {
		_ = chrome.Process.Kill()
	}
	chrome = nil
}

func alive() bool {
	resp, err := cdpHTTP.Get(cdpAddress() + "/json/version")
	if err != nil {
		return false
	}
	resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// aliveAt 探某个端口上有没有在应答的 CDP（不动 CDPBase）。
func aliveAt(port int) bool {
	resp, err := cdpHTTP.Get(fmt.Sprintf("http://127.0.0.1:%d/json/version", port))
	if err != nil {
		return false
	}
	resp.Body.Close()
	return resp.StatusCode == http.StatusOK
}

// profileInstancePort 找「已经在跑、且用同一个 user-data-dir 的 Chrome 浏览器进程」的调试端口，
// 没有则 0。用 ps 而不是 /proc：macOS 也要能用。
func profileInstancePort(profile string) int {
	if profile == "" {
		return 0
	}
	out, err := exec.Command("ps", "-eo", "args=").Output()
	if err != nil {
		return 0
	}
	return parseProfilePort(string(out), profile)
}

// parseProfilePort 从 ps 输出里挑出那台浏览器进程的 --remote-debugging-port。
// 逐 token 精确比对 user-data-dir（子串匹配会让 /tmp/x 命中 /tmp/x-headed），并跳过
// 带 --type= 的子进程（renderer/gpu 也带着同样的 profile 和端口参数）。
func parseProfilePort(psOut, profile string) int {
	want := "--user-data-dir=" + profile
	for _, line := range strings.Split(psOut, "\n") {
		port, hasProfile, isChild := 0, false, false
		for _, f := range strings.Fields(line) {
			switch {
			case f == want:
				hasProfile = true
			case strings.HasPrefix(f, "--type="):
				isChild = true
			case strings.HasPrefix(f, "--remote-debugging-port="):
				port, _ = strconv.Atoi(strings.TrimPrefix(f, "--remote-debugging-port="))
			}
		}
		if hasProfile && !isChild && port > 0 {
			return port
		}
	}
	return 0
}

// browserUA 取这台 Chrome 的原生 User-Agent（/json/version 的 "User-Agent" 字段）。
// 用于手机模式切回桌面时复位 UA——CDP 没有 clearUserAgentOverride，只能再 set 回默认值。
func browserUA() string {
	resp, err := cdpHTTP.Get(cdpAddress() + "/json/version")
	if err != nil {
		return ""
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var v struct {
		UserAgent string `json:"User-Agent"`
	}
	_ = json.Unmarshal(b, &v)
	// 无头模式下原生 UA 可能带 "HeadlessChrome" 标记，一眼被站点识别为自动化；抹掉这个词，
	// 其余版本号/平台信息不变，看起来和有头 Chrome 一致。
	return strings.Replace(v.UserAgent, "HeadlessChrome", "Chrome", 1)
}

// isUserTab 判断一个 page target 是不是「用户的标签页」。
//
// Chrome 把自己那套界面也报成 type=page：地址栏下拉（chrome://omnibox-popup.top-chrome/）、
// 标签搜索、各种侧边栏，都是 chrome://<something>.top-chrome/ 的 WebUI。它们混在 /json 里，
// 于是标签条上多出一条关不掉的标签——/json/close 对浏览器界面无效，它还会随下一次输入再冒出来；
// 更糟的是它常常排在首位，而首位标签的变化被前台跟随当成「用户切了标签」，镜像会跟着跳过去。
// DevTools 前端（devtools://）同理：它是我们另开的调试窗口，不是被镜像的标签。
func isUserTab(t target) bool {
	u := strings.ToLower(t.URL)
	if strings.HasPrefix(u, "devtools://") || strings.HasPrefix(u, "chrome-untrusted://") {
		return false
	}
	if rest, ok := strings.CutPrefix(u, "chrome://"); ok {
		host, _, _ := strings.Cut(rest, "/")
		if strings.Contains(host, "top-chrome") { // chrome://settings 这类真页面照常留下
			return false
		}
	}
	return true
}

// rawTargets 是 /json 的原样结果：什么都不过滤。
// 「这个 id 还在不在」必须问它——问 listPages 的话，被过滤掉的目标看起来永远是「已经关了」。
func rawTargets() []target {
	resp, err := cdpHTTP.Get(cdpAddress() + "/json")
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	var ts []target
	if json.Unmarshal(b, &ts) != nil {
		return nil
	}
	return ts
}

// listPages 返回所有 page 类型的标签页（过滤掉 service worker / iframe 等其它 target，
// 以及 Chrome 自己的界面——见 isUserTab）。
func listPages() []target {
	ts := rawTargets()
	pages := ts[:0]
	for _, t := range ts {
		if t.Type == "page" && isUserTab(t) {
			pages = append(pages, t)
		}
	}
	return pages
}

// targetWS 返回指定标签页的 CDP WebSocket 地址。
// id 为空 → 取第一个 page；一个 page 都没有时新建一个空白页。
func targetWS(id string) (string, error) {
	pages := listPages()
	for _, t := range pages {
		if t.WebSocketDebuggerURL == "" {
			continue
		}
		if id == "" || t.ID == id {
			return t.WebSocketDebuggerURL, nil
		}
	}
	if id != "" {
		return "", fmt.Errorf("标签页不存在: %s", id)
	}
	// 没有任何 page，开一个空白页再找
	_, _ = newTab("about:blank")
	for _, t := range listPages() {
		if t.WebSocketDebuggerURL != "" {
			return t.WebSocketDebuggerURL, nil
		}
	}
	return "", fmt.Errorf("找不到可用的 page 目标")
}

// newTab 新建一个标签页（Chrome ≥111 要求 PUT /json/new），返回新标签 id。
func newTab(rawURL string) (string, error) {
	u := cdpAddress() + "/json/new"
	if rawURL != "" {
		u += "?" + url.QueryEscape(rawURL)
	}
	req, _ := http.NewRequest(http.MethodPut, u, nil)
	resp, err := cdpHTTP.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return "", fmt.Errorf("新建标签页失败: %s", resp.Status)
	}
	b, _ := io.ReadAll(resp.Body)
	var t target
	_ = json.Unmarshal(b, &t)
	markFront(t.ID) // 新标签即前置，watcher 据此广播让镜像面板跟到新标签
	return t.ID, nil
}

// ErrNotClosable：Chrome 收下了关闭请求，但那一页还在。
// 浏览器界面页就是这样（chrome://omnibox-popup.top-chrome/ 之类）：/json/close 照样回
// "Target is closing"，列表里却一直在——它是浏览器窗口的一部分，不是标签，关不掉。
// 实测：/json/close 回 "Target is closing"、CDP Target.closeTarget 回 {success:true}，
// 两条路都是嘴上答应，那一页原封不动还在列表里。
var ErrNotClosable = errors.New("这一页是 Chrome 的浏览器界面（不是标签页），Chrome 不允许关闭")

// closeTab 关闭指定标签页，并确认它真的没了。
//
// 不能只看 /json/close 的回复：它对关不掉的目标也回 200 "Target is closing"，
// 于是前端以为关成功，下一次 3 秒轮询那一行又回来了——用户看到的就是「这标签关不掉」。
func closeTab(id string) error {
	resp, err := cdpHTTP.Get(cdpAddress() + "/json/close/" + id)
	if err != nil {
		return err
	}
	resp.Body.Close()
	for i := 0; i < 6; i++ { // 关闭是异步的，给它 ~900ms 消失
		time.Sleep(150 * time.Millisecond)
		if !targetExists(id) {
			return nil
		}
	}
	return ErrNotClosable
}

func targetExists(id string) bool {
	for _, t := range rawTargets() {
		if t.ID == id {
			return true
		}
	}
	return false
}

// 最近被「前置」的标签追踪（用户在镜像面板点标签、或经 REST 激活）。watcher 据此广播
// 「活跃标签」给前端做自动跟随。chrome-cli 走的是裸 CDP（不经这层 HTTP API，见
// driver.mjs），它对目标标签发的 /json/activate 会被下面 watchFrontTab 的 /json 顺序
// 兜底捕捉到——两条路径互补：本函数覆盖「经后端」的前置，兜底覆盖「绕过后端直连
// CDP」的前置。gen 单调递增供 watcher 判变。
var (
	frontMu  sync.Mutex
	frontID  string
	frontGen uint64
)

func markFront(id string) {
	if id == "" {
		return
	}
	frontMu.Lock()
	if id != frontID {
		frontID = id
		frontGen++
	}
	frontMu.Unlock()
}

func frontSnapshot() (string, uint64) {
	frontMu.Lock()
	defer frontMu.Unlock()
	return frontID, frontGen
}

// activateTab 把指定标签页在 Chrome 里前置（让 agent 的前台焦点与正在镜像的一致）。
func activateTab(id string) error {
	resp, err := cdpHTTP.Get(cdpAddress() + "/json/activate/" + id)
	if err != nil {
		return err
	}
	resp.Body.Close()
	markFront(id)
	return nil
}

// call 发一条 CDP 命令并等待匹配 id 的响应（仅用于一次性专用连接，与帧 goroutine 不共用读端）。
func (c *cdp) call(method string, params map[string]any) (json.RawMessage, error) {
	c.mu.Lock()
	c.id++
	id := c.id
	err := c.ws.WriteJSON(map[string]any{"id": id, "method": method, "params": params})
	c.mu.Unlock()
	if err != nil {
		return nil, err
	}
	_ = c.ws.SetReadDeadline(time.Now().Add(5 * time.Second))
	for {
		_, data, err := c.ws.ReadMessage()
		if err != nil {
			return nil, err
		}
		var r struct {
			ID     int             `json:"id"`
			Result json.RawMessage `json:"result"`
			Error  *struct {
				Message string `json:"message"`
			} `json:"error"`
		}
		if json.Unmarshal(data, &r) != nil || r.ID != id {
			continue // 事件(无 id)或其它响应，跳过
		}
		if r.Error != nil {
			return nil, fmt.Errorf("%s", r.Error.Message)
		}
		return r.Result, nil
	}
}

// withTab 临时连到某标签页的 CDP，执行 fn 后断开。
func withTab(id string, fn func(*cdp) error) error {
	ws, err := targetWS(id)
	if err != nil {
		return err
	}
	back, _, err := websocket.DefaultDialer.Dial(ws, nil)
	if err != nil {
		return err
	}
	defer back.Close()
	connection := &cdp{ws: back}
	cfgStore.mu.Lock()
	configured := cfgStore.file != ""
	cfgStore.mu.Unlock()
	if configured {
		identity, err := currentBrowserIdentity()
		if err != nil {
			return err
		}
		token := strconv.FormatInt(time.Now().UnixNano(), 10)
		if _, err = tabCatalog(browsertabs.Event{Action: "start", BrowserID: identity, TargetID: id, Token: token}); err != nil {
			return err
		}
		known := false
		defer func() {
			_, _ = tabCatalog(browsertabs.Event{Action: "finish", BrowserID: identity, TargetID: id, Token: token, Known: known})
		}()
		if _, err = connection.call("Page.setWebLifecycleState", map[string]any{"state": "active"}); err != nil {
			return err
		}
		err = fn(connection)
		known = err == nil
		return err
	}
	return fn(connection)
}

func tabReload(id string) error {
	return withTab(id, func(c *cdp) error { _, err := c.call("Page.reload", nil); return err })
}

func tabNavigate(id, url string) error {
	return withTab(id, func(c *cdp) error {
		result, err := c.call("Page.navigate", map[string]any{"url": url})
		if err != nil {
			return err
		}
		var navigation struct {
			ErrorText string `json:"errorText"`
		}
		if err := json.Unmarshal(result, &navigation); err != nil {
			return err
		}
		if navigation.ErrorText != "" {
			return fmt.Errorf("%s", navigation.ErrorText)
		}
		return nil
	})
}

// tabHistory 按 delta（-1 后退 / +1 前进）走导航历史；到边界则静默不动。
func tabHistory(id string, delta int) error {
	return withTab(id, func(c *cdp) error {
		res, err := c.call("Page.getNavigationHistory", nil)
		if err != nil {
			return err
		}
		var h struct {
			CurrentIndex int `json:"currentIndex"`
			Entries      []struct {
				ID int `json:"id"`
			} `json:"entries"`
		}
		if err := json.Unmarshal(res, &h); err != nil {
			return err
		}
		i := h.CurrentIndex + delta
		if i < 0 || i >= len(h.Entries) {
			return nil // 无可后退/前进
		}
		_, err = c.call("Page.navigateToHistoryEntry", map[string]any{"entryId": h.Entries[i].ID})
		return err
	})
}
