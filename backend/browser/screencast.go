// screencast.go：浏览器镜像的 CDP 桥核心 + 传输 sink 抽象。
//
// 传输优化（针对 frp / 低带宽场景）：
//
//   - 二进制帧：JPEG 字节直接走 sink binary（省掉 base64 的 33% 膨胀 + 两端编解码）
//     帧格式 = [w:u16 LE][h:u16 LE][seq:u16 LE][jpeg...]
//
//   - 自适应码率（?auto=1）：以「发出→收到 ack」的耗时(deliveryMs)为信号，太慢降档、
//     有余量升档，动态调 JPEG 质量 / 分辨率(maxWidth/Height) / everyNthFrame。
//
//     CDP  → 前端：Page.startScreencast 的 JPEG 帧（二进制）
//     前端 → CDP：鼠标/键盘/滚轮/导航（仅 control=1 时转发输入；默认只读镜像）
//
// 传输层（写帧 + 背压）被抽象为 frameSink（见下）：
//
//   - wsSink（screencast_ws.go）：现有 gorilla WebSocket 实现，走 /api/browser/stream，
//     信用·ack 背压（在途帧限窗，慢链路丢中间帧）。P2P 回退路径，行为不变。
//   - dcSink（screencast_dc.go）：WebRTC DataChannel（media PC）实现，不可靠·无序通道，
//     背压用 BufferedAmount()（超高水位丢当前帧，符合不可靠语义）。
//
// 核心 runScreencast 不感知底层是 WS 还是 DataChannel：只调 sink 的 writeBinary /
// writeText，并把入站控制 JSON 经 onCtrl 喂回原逻辑（ping/ack/nav/emulate/quality/输入）。
package browser

import (
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  4096,
	WriteBufferSize: 1 << 16,
	// 同源校验：抄 pty/stream 那套（Origin host 必须等于请求 Host）
	CheckOrigin: func(r *http.Request) bool {
		origin := r.Header.Get("Origin")
		if origin == "" {
			return true
		}
		i := strings.Index(origin, "://")
		return i >= 0 && origin[i+3:] == r.Host
	},
}

// browserClip 是「浏览器内部剪贴板」：Ctrl+C 存远端当前选区，Ctrl+V 在前端读不到本机剪贴板
// （无权限/非安全上下文）时用它兜底 insertText。全局共享 → A 标签复制、B 标签粘贴也通。
var browserClip struct {
	mu   sync.Mutex
	text string
}

// cdp 是到单个 page 目标的 CDP 连接；WriteJSON 非并发安全，故加锁串行写。
type cdp struct {
	ws *websocket.Conn
	mu sync.Mutex
	id int
}

func (c *cdp) send(method string, params map[string]any) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.id++
	_ = c.ws.WriteJSON(map[string]any{"id": c.id, "method": method, "params": params})
}

// sendID 同 send，但返回本次请求的 CDP id，用于在响应读取循环里匹配回包（复制选区取返回值）。
func (c *cdp) sendID(method string, params map[string]any) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.id++
	id := c.id
	_ = c.ws.WriteJSON(map[string]any{"id": id, "method": method, "params": params})
	return id
}

// frameSink 是镜像传输层抽象：核心只用它「写帧 / 写控制 / 收控制 / 关闭」，不感知底层是
// gorilla WebSocket 还是 WebRTC DataChannel。见文件头。
//
//   - writeBinary(frame)：发一帧（二进制）；出错返回 err → 核心停机。
//   - writeText(v)：发一条控制 JSON（level/pong/error/copied/newtab）。
//   - onCtrl(fn)：注册入站控制回调（前端发来的 JSON 文本，逐条喂 fn）。核心在此注册后，
//     由 sink 自己的读循环（WS）或 DataChannel.OnMessage（DC）驱动调用。
//   - awaitSlot()：阻塞直到「可以发下一帧」——WS 有信用即可，DC 用 BufferedAmount 限流
//     （水位过高就丢帧：返回 (0,false) 表示本轮跳过不发）。返回的 seq 是本帧序号（帧头用）。
//     ok=false 且未关闭 = 丢帧继续；closed=true = 核心退出。
//   - onAck(n)：ack 一帧（归还信用/记 deliveryMs 供自适应）。WS/DC 都调，DC 无信用只记时延。
//   - closed()：sink 是否已关闭（读循环退出/对端断）。
//   - close()：主动关闭 sink（核心侧发生致命错误时调）。
//   - wait()：阻塞直到 sink 关闭，作为 runScreencast 的生命周期驱动。
type frameSink interface {
	writeBinary(b []byte) error
	writeText(v any) error
	onCtrl(fn func([]byte))
	close()
	closed() bool
	wait()

	// 帧调度 / 背压：核心的发送 goroutine 用这三者。sink 内部维护自己的背压状态
	// （WS：信用+ack；DC：BufferedAmount 丢帧），核心只负责产帧与解码。
	awaitSlot() (seq uint16, ok bool)
	onAck(n uint16) (deliveryMs float64, matched bool)
}

func atoiDefault(s string, d int) int {
	if n, err := strconv.Atoi(s); err == nil {
		return n
	}
	return d
}

func atofDefault(s string, d float64) float64 {
	if f, err := strconv.ParseFloat(s, 64); err == nil {
		return f
	}
	return d
}

// lvl 是一档画质/分辨率/帧率组合；自适应在 ladder 上上下移动。
type lvl struct {
	q, w, h, nth int
	name         string
}

// 自适应档位阶梯：从省流到超清。低档降分辨率/降质/抽帧，保「跟手」；高档保清晰。
var ladder = []lvl{
	{28, 960, 600, 2, "省流"},
	{40, 1280, 800, 2, "流畅"},
	{52, 1280, 800, 1, "标清"},
	{64, 1600, 1000, 1, "清晰"},
	{76, 1920, 1200, 1, "高清"},
	{90, 3840, 2160, 1, "超清"}, // 顶档放宽到 4K 采集上限，配合前端 ≥2x 超采样(desktopDpr)保文字清晰
}

const autoStart = 2 // 自适应初始档（标清，快速起步再按链路上探）

var rendererProbeInterval = 3 * time.Second
var rendererProbeTimeout = 9 * time.Second

// cursorScript 注入被镜像页：画一个跟随指针的光点，点击时在光点处绽放涟漪。
// 无论输入来自用户接管（Input.dispatchMouseEvent）还是 agent 经 chrome-cli/CDP 操作，
// 都会触发页面自身的 mousemove/mousedown 监听 → 观看端由此看清「谁在哪里点/在哪」，
// 而不是像前端本地涟漪(addRipple)那样只在查看端画、进不了实际截屏帧。
// __bladeCur 防重复注入；__bladeCurHide 供用户接管期间短暂抑制（人在面板上已有系统光标，
// 不需要双光标）。
const cursorScript = `(() => {
  if (window.__bladeCur) return; window.__bladeCur = 1;
  const cur = document.createElement('div');
  cur.style.cssText = 'position:fixed;left:0;top:0;z-index:2147483647;width:14px;height:14px;' +
    'margin:-7px 0 0 -7px;border-radius:50%;background:radial-gradient(circle,#4d9bff 0%,#1f6feb 60%,rgba(31,111,235,0) 100%);' +
    'box-shadow:0 0 10px 3px rgba(31,111,235,.6);pointer-events:none;opacity:0;transition:opacity .3s;will-change:transform';
  const style = document.createElement('style');
  style.textContent = '@keyframes __bladeRip{from{transform:scale(.35);opacity:.95}to{transform:scale(2.4);opacity:0}}';
  const mount = () => {
    (document.head || document.documentElement).appendChild(style);
    (document.body || document.documentElement).appendChild(cur);
  };
  if (document.body) mount(); else addEventListener('DOMContentLoaded', mount);
  let hideTimer;
  let suppressUntil = 0;
  window.__bladeCurHide = (ms) => { suppressUntil = Date.now() + (ms || 1200); cur.style.opacity = '0'; };
  const show = (x, y) => {
    if (Date.now() < suppressUntil) return;
    cur.style.transform = 'translate(' + x + 'px,' + y + 'px)';
    cur.style.opacity = '1';
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => { cur.style.opacity = '0'; }, 2000);
  };
  addEventListener('mousemove', (e) => show(e.clientX, e.clientY), { capture: true, passive: true });
  addEventListener('mousedown', (e) => {
    if (Date.now() < suppressUntil) return;
    show(e.clientX, e.clientY);
    const rip = document.createElement('div');
    rip.style.cssText = 'position:fixed;z-index:2147483646;left:' + (e.clientX - 12) + 'px;top:' + (e.clientY - 12) +
      'px;width:24px;height:24px;border-radius:50%;border:3px solid #1f6feb;pointer-events:none;' +
      'animation:__bladeRip .5s ease-out forwards';
    (document.body || document.documentElement).appendChild(rip);
    setTimeout(() => rip.remove(), 600);
  }, { capture: true, passive: true });
})()`

// keyInfo 把 DOM KeyboardEvent.key 映射到 CDP 需要的 (code, windowsVirtualKeyCode, text)。
// 只覆盖非可打印的常用键；可打印字符走 Input.insertText，不经过这里。
func keyInfo(key string) (code string, vk int, text string) {
	switch key {
	case "Enter":
		return "Enter", 13, "\r"
	case "Tab":
		return "Tab", 9, "\t"
	case "Backspace":
		return "Backspace", 8, ""
	case "Delete":
		return "Delete", 46, ""
	case "Escape":
		return "Escape", 27, ""
	case "ArrowLeft":
		return "ArrowLeft", 37, ""
	case "ArrowUp":
		return "ArrowUp", 38, ""
	case "ArrowRight":
		return "ArrowRight", 39, ""
	case "ArrowDown":
		return "ArrowDown", 40, ""
	case "Home":
		return "Home", 36, ""
	case "End":
		return "End", 35, ""
	case "PageUp":
		return "PageUp", 33, ""
	case "PageDown":
		return "PageDown", 34, ""
	}
	return "", 0, ""
}

// buildFrame 打包一帧为二进制：[w][h][seq] 各 2 字节小端 + JPEG 原始字节。
func buildFrame(jpeg []byte, w, h int, seq uint16) []byte {
	b := make([]byte, 6+len(jpeg))
	binary.LittleEndian.PutUint16(b[0:], uint16(w))
	binary.LittleEndian.PutUint16(b[2:], uint16(h))
	binary.LittleEndian.PutUint16(b[4:], seq)
	copy(b[6:], jpeg)
	return b
}

func nowMs() int64 { return time.Now().UnixMilli() }

func absInt(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func absFloat(n float64) float64 {
	if n < 0 {
		return -n
	}
	return n
}

// scOptions 是一次镜像会话的入参（从 WS query 或 DataChannel label 的 query 解析）。
// 与底层传输无关，故 WS handler 与 DataChannel handler 共用。
type scOptions struct {
	expectedBrowser string
	target          string // 目标标签页 id（空=第一个）
	control         bool   // 是否转发鼠标/键盘输入（默认只读镜像）
	auto            bool   // 自适应码率
	q               int    // 手动模式初始 JPEG 质量（10~100；auto 时忽略）
	// 初始视口覆盖（一般由前端连上后发 emulate 决定，这里只是兜底）
	mobile bool
	mw, mh int
	dpr    float64
	ua     string
}

// runScreencast 是镜像 CDP 桥核心：连 Chrome page、按 sink 收发帧与控制，自适应调档。
// 不感知底层传输（WS/DataChannel）——只调 sink 的 writeBinary/writeText/awaitSlot 等。
// 阻塞直到 sink 关闭或 CDP 断开。sink 的 wait() 驱动整体生命周期。
func runScreencast(sink frameSink, opts scOptions) {
	wsURL, err := targetForScreencast(opts)
	if err != nil {
		_ = sink.writeText(map[string]any{"type": "error", "msg": err.Error()})
		return
	}
	back, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		_ = sink.writeText(map[string]any{"type": "error", "msg": "连接 Chrome 失败: " + err.Error()})
		return
	}
	defer back.Close()
	conn := &cdp{ws: back}
	if _, err := conn.call("Runtime.evaluate", map[string]any{"expression": "document.readyState", "returnByValue": true}); err != nil {
		_ = sink.writeText(map[string]any{"type": "error", "msg": "BROWSER_PAGE_UNRESPONSIVE"})
		return
	}
	_ = back.SetReadDeadline(time.Time{})
	control := opts.control
	auto := opts.auto
	defaultUA := browserUA() // 浏览器原生 UA，切回桌面时用它复位（CDP 没有 clearUserAgentOverride）

	// ── 自适应共享状态（背压/信用在 sink 内，这里只保留自适应 + CDP 侧状态） ──
	var mu sync.Mutex
	cond := sync.NewCond(&mu)
	type pend struct {
		b64  string
		w, h int
	}
	var (
		pending *pend // 最新一帧（未发出的），新帧覆盖旧帧 = latest-only 丢帧
		ewma    float64
		level   = autoStart // 当前档位（仅 auto 模式移动）
		closed  bool
		frameW  = 1280 // 最近一帧/视口 CSS 宽高（流帧 metadata 缺失时补帧头用）
		frameH  = 800
		// prevMobile/prevUA 记当前生效的「机型态」，用于判断 emulate 是否真切换了设备/UA。
		copyReqID int // 复制选区的 Runtime.evaluate 请求 id；读取循环据此匹配回包(0=无在途)
		// 视口自愈：CDP device metrics 覆盖是「最后写入者赢」，chrome-cli 截图等外部会话会把本会话
		// 的覆盖踩掉且退出后仍卡在渲染器上 → 布局重排、用户看到内容突然变大/变小。流帧 metadata
		// 偏离期望视口时防抖重设抢回。详见 docs/development/browser-mirror.md。
		expW, expH   int    // 本会话期望的视口 CSS 宽高（0 = 无覆盖，不自愈）
		reassert     func() // 重发本会话 device metrics 覆盖
		lastReassert int64  // 上次自愈时刻(ms)；600ms 防抖，避免与另一活跃会话打乒乓
		lastStreamMs int64  // 最近一帧正常 screencast 到达时间；流仍活跃时无需额外请求补帧
		// 连击识别：CDP Input.dispatchMouseEvent 要求调用方显式给 clickCount，不会像真实 OS
		// 那样按时间/位置自动识别双击、三击——不补的话网页的 dblclick 监听永远不会触发。
		lastClickAt            int64 // 上次 mousedown 时刻(ms)
		lastClickX, lastClickY float64
		lastClickBtn           string
		clickStreak            int
		probeID                int
		probeAt                time.Time
	)

	// 初始档：auto 用阶梯，手动用前端给的 q（分辨率给足，质量听用户）
	cur := ladder[autoStart]
	if !auto {
		q := opts.q
		if q == 0 {
			q = 80
		}
		if q < 10 {
			q = 10
		} else if q > 100 {
			q = 100
		}
		cur = lvl{q: q, w: 3840, h: 2160, nth: 1, name: "手动"}
	}
	applyLevel := func(l lvl) {
		conn.send("Page.startScreencast", map[string]any{
			"format": "jpeg", "quality": l.q,
			"maxWidth": l.w, "maxHeight": l.h, "everyNthFrame": l.nth,
		})
	}
	setFrameSize := func(w, h int) {
		if w <= 0 || h <= 0 {
			return
		}
		mu.Lock()
		frameW, frameH = w, h
		mu.Unlock()
	}
	// 强制补帧 = 重发 Page.startScreencast（无需 stop）。Chrome 收到后立即吐一帧当前画面，
	// 走与流帧完全相同的管线（同 metadata/同降采样）→ 天然像素级一致。
	// 绝不能用 Page.captureScreenshot：它 fromSurface 出图，模拟视口高于 Chrome 窗口时
	// （手机竖屏 vp 2226 > 窗口 800）会临时改表面尺寸 → 真实视口被扰动（实测 metadata 跳到
	// 1380×2400、蹦出 2760×4800 巨帧）→ 页面重排、画面缩成一块乱跳。见 docs/development/browser-mirror.md。
	forceFrame := func() {
		mu.Lock()
		if closed {
			mu.Unlock()
			return
		}
		// cur / auto 会被前端「切画质」消息在运行中改写，故一律在锁内读，避免与切换竞态。
		l := cur
		if auto && level >= 0 && level < len(ladder) {
			l = ladder[level]
		}
		mu.Unlock()
		applyLevel(l)
	}
	var refreshMu sync.Mutex
	refreshVersion := 0
	lastForced := time.Time{}
	scheduleForceFrame := func() {
		refreshMu.Lock()
		refreshVersion++
		version := refreshVersion
		refreshMu.Unlock()

		// 严格 trailing debounce：连续输入合并为一次；正常 screencast 仍在产帧时完全不补。
		// 旧实现沿用截图时代的 leading/trailing 双连发，一次按键可能重启 screencast 2~4 次，
		// 即使 latest-only 最终丢帧，Chrome/CDP 仍会承担重复 JPEG 编码与 base64 传输开销。
		go func() {
			time.Sleep(150 * time.Millisecond)
			refreshMu.Lock()
			if version != refreshVersion || time.Since(lastForced) < 500*time.Millisecond {
				refreshMu.Unlock()
				return
			}
			mu.Lock()
			streamQuiet := nowMs()-lastStreamMs >= 250
			mu.Unlock()
			if streamQuiet {
				lastForced = time.Now()
			}
			refreshMu.Unlock()
			if streamQuiet {
				forceFrame()
			}
		}()
	}
	conn.send("Page.enable", nil)

	// 虚拟光标：往被镜像页注入轻量脚本，监听 mousemove/mousedown 画光标+点击涟漪。
	// addScriptToEvaluateOnNewDocument 覆盖后续导航，Runtime.evaluate 覆盖当前已加载页；
	// __bladeCur 防重复注入。
	conn.send("Page.addScriptToEvaluateOnNewDocument", map[string]any{"source": cursorScript})
	conn.send("Runtime.evaluate", map[string]any{"expression": cursorScript})

	// 只给非本人操作画光标：人在面板上已有系统光标，双光标观感怪 —— 用户接管的每次鼠标
	// 输入前节流通知页面暂停虚拟光标 1.5s。500ms 节流：连续操作最多每半秒发一次。
	var lastCurHide int64
	hideCursorForUser := func() {
		now := nowMs()
		if now-lastCurHide < 500 {
			return
		}
		lastCurHide = now
		conn.send("Runtime.evaluate", map[string]any{"expression": "window.__bladeCurHide&&window.__bladeCurHide(1500)"})
	}

	// 前台标签跟随：谁在操作、operating 到哪个标签，就把这个连接对应的镜像面板广播过去
	// 跟上（前端据此实现"首连即同步到 agent 当前标签"和"agent 切标签面板自动跟随"）。
	// 活跃标签以 markFront 的显式记录（frontSnapshot）为准——它在经后端 REST 前置
	// （用户点标签栏、TabActivate、newTab）时更新；chrome-cli 走裸 CDP 直连 Chrome（见
	// driver.mjs），不经这层 HTTP API，markFront 感知不到，所以再叠一层 /json 顺序兜底：
	// 首位标签变化也视为一次前置，兜的正是"绕过后端直连 CDP"这条路径。
	watchDone := make(chan struct{})
	defer close(watchDone)
	go func() {
		lastGen := uint64(0)
		lastOrderFirst := ""
		synced := false
		tick := time.NewTicker(1 * time.Second)
		defer tick.Stop()
		for {
			select {
			case <-watchDone:
				return
			case <-tick.C:
			}
			pages := listPages()
			if len(pages) == 0 {
				continue
			}
			if pages[0].ID != lastOrderFirst {
				lastOrderFirst = pages[0].ID
				markFront(pages[0].ID)
			}
			id, gen := frontSnapshot()
			if synced && gen == lastGen {
				continue
			}
			lastGen = gen
			var active *target
			for i := range pages {
				if pages[i].ID == id {
					active = &pages[i]
					break
				}
			}
			if active == nil { // 还没有前置记录（刚启动）：退回第一个标签，至少给个基线
				active = &pages[0]
			}
			synced = true
			list := make([]map[string]any, 0, len(pages))
			for _, p := range pages {
				list = append(list, map[string]any{"id": p.ID, "title": p.Title, "url": p.URL})
			}
			if sink.writeText(map[string]any{"type": "active", "id": active.ID, "url": active.URL, "tabs": list}) != nil {
				return
			}
		}
	}()

	// 手机模式：把本镜像连接对应的渲染器切到移动视口（设备指标/触摸/UA 覆盖作用于整个
	// page 渲染，故镜像里看到的就是真实移动端布局，agent 用 chrome-cli 截同一页也是移动端）。
	//
	// 关键设计：设备切换【不重连】，由前端在本条连接上发 {type:'emulate'} 消息现场切换。
	// 因为 CDP 的 setDeviceMetricsOverride 是「会话级」——clearDeviceMetricsOverride 只能撤销
	// 【本会话】设的覆盖，撤不掉别会话留的。若每次切换都重连，旧会话的 defer 清理与新连接会
	// 抢跑（来回切尤其容易卡住）。改成同一会话 set/clear，既不泄漏也无竞态。
	applyMobile := func(mw, mh int, dpr float64, ua string) {
		setFrameSize(mw, mh)
		metrics := map[string]any{
			"width": mw, "height": mh, "deviceScaleFactor": dpr, "mobile": true,
			"screenWidth": mw, "screenHeight": mh,
		}
		mu.Lock()
		expW, expH = mw, mh
		reassert = func() { conn.send("Emulation.setDeviceMetricsOverride", metrics) }
		mu.Unlock()
		conn.send("Emulation.setDeviceMetricsOverride", metrics)
		conn.send("Emulation.setTouchEmulationEnabled", map[string]any{"enabled": true, "maxTouchPoints": 5})
		conn.send("Emulation.setEmitTouchEventsForMouse", map[string]any{"enabled": true, "configuration": "mobile"})
		if ua != "" { // 设备 UA 由前端按机型下发，后端只透传
			conn.send("Emulation.setUserAgentOverride", map[string]any{"userAgent": ua})
		}
	}
	// 桌面模式：用观看端的原生尺寸（前端下发的 CSS 宽高 + 真实 DPR）覆盖视口，使镜像里的
	// 桌面布局与你屏幕一致、随窗口大小自适应——不再被 Chrome 启动时的 --window-size(1280×800) 限死。
	// w<=0 时退化为 clearMobile（彻底不覆盖，用 Chrome 原生窗口尺寸）。
	applyDesktop := func(w, h int, dpr float64) {
		if w <= 0 || h <= 0 {
			mu.Lock()
			expW, expH, reassert = 0, 0, nil // 无覆盖 → 不自愈
			mu.Unlock()
			conn.send("Emulation.clearDeviceMetricsOverride", nil)
		} else {
			setFrameSize(w, h)
			metrics := map[string]any{
				"width": w, "height": h, "deviceScaleFactor": dpr, "mobile": false,
				"screenWidth": w, "screenHeight": h,
			}
			mu.Lock()
			expW, expH = w, h
			reassert = func() { conn.send("Emulation.setDeviceMetricsOverride", metrics) }
			mu.Unlock()
			conn.send("Emulation.setDeviceMetricsOverride", metrics)
		}
		conn.send("Emulation.setTouchEmulationEnabled", map[string]any{"enabled": false})
		conn.send("Emulation.setEmitTouchEventsForMouse", map[string]any{"enabled": false})
		if defaultUA != "" { // 复位 UA，否则从手机切回桌面 navigator.userAgent 还卡在手机 UA
			conn.send("Emulation.setUserAgentOverride", map[string]any{"userAgent": defaultUA})
		}
	}
	clearAll := func() {
		mu.Lock()
		expW, expH, reassert = 0, 0, nil
		mu.Unlock()
		conn.send("Emulation.clearDeviceMetricsOverride", nil)
		conn.send("Emulation.setTouchEmulationEnabled", map[string]any{"enabled": false})
		conn.send("Emulation.setEmitTouchEventsForMouse", map[string]any{"enabled": false})
		if defaultUA != "" {
			conn.send("Emulation.setUserAgentOverride", map[string]any{"userAgent": defaultUA})
		}
	}
	overrideOn := false // 本会话当前是否设了任何视口覆盖；仅在主消息 goroutine 与其后的 defer 读写
	prevMobile, prevUA := false, ""
	if opts.mobile { // 初始态兜底（一般由前端连上后发 emulate 决定）
		applyMobile(orDefaultInt(opts.mw, 390), orDefaultInt(opts.mh, 844), orDefaultFloat(opts.dpr, 3), opts.ua)
		overrideOn = true
		prevMobile, prevUA = true, opts.ua
	}
	// 断开前清掉本会话覆盖（在 back.Close 之前，conn 仍可写）→ 不泄漏给后续镜像 / chrome-cli / DevTools。
	defer func() {
		if overrideOn {
			clearAll()
		}
	}()
	applyLevel(cur)

	shutdown := func() {
		mu.Lock()
		closed = true
		cond.Broadcast()
		mu.Unlock()
		sink.close()
	}

	// CDP → 服务端：收帧即 ack Chrome（保持产帧、画面最新），最新帧塞进单槽（丢旧帧）
	go func() {
		defer shutdown()
		for {
			_, data, err := back.ReadMessage()
			if err != nil {
				return
			}
			var msg struct {
				ID     int    `json:"id"`
				Method string `json:"method"`
				Params struct {
					Data      string `json:"data"`
					SessionID int    `json:"sessionId"`
					Metadata  struct {
						DeviceWidth  float64 `json:"deviceWidth"`
						DeviceHeight float64 `json:"deviceHeight"`
					} `json:"metadata"`
				} `json:"params"`
				Result struct {
					Result struct {
						Value string `json:"value"`
					} `json:"result"`
				} `json:"result"`
			}
			if json.Unmarshal(data, &msg) != nil {
				continue
			}
			if msg.Method != "Page.screencastFrame" {
				// 被镜像页打开新窗口/标签（target=_blank、window.open、表单提交等）→ 通知前端跟过去
				if msg.Method == "Page.windowOpen" {
					_ = sink.writeText(map[string]any{"type": "newtab"})
					continue
				}
				// 非帧消息：可能是「复制选区」的 Runtime.evaluate 回包，按 id 匹配后转发给前端
				if msg.ID != 0 {
					mu.Lock()
					if msg.ID == probeID {
						probeID = 0
					}
					hit := copyReqID != 0 && msg.ID == copyReqID
					if hit {
						copyReqID = 0
					}
					mu.Unlock()
					if hit {
						txt := msg.Result.Result.Value
						browserClip.mu.Lock() // 存进浏览器内部剪贴板，供 Ctrl+V 兜底（不依赖本机剪贴板）
						browserClip.text = txt
						browserClip.mu.Unlock()
						_ = sink.writeText(map[string]any{"type": "copied", "text": txt})
					}
				}
				continue
			}
			conn.send("Page.screencastFrameAck", map[string]any{"sessionId": msg.Params.SessionID})
			var heal func()
			mu.Lock()
			w, h := int(msg.Params.Metadata.DeviceWidth), int(msg.Params.Metadata.DeviceHeight)
			if w > 0 && h > 0 {
				frameW, frameH = w, h
			} else {
				w, h = frameW, frameH
			}
			// 视口自愈：帧的真实视口偏离本会话期望（容差 ±2px）→ 有外部会话踩了覆盖，防抖重设抢回。
			// 异常帧不能继续交给前端，否则即使下一帧恢复，用户仍会看到一次布局/纵横比跳变。
			mismatched := expW > 0 && w > 0 && (absInt(w-expW) > 2 || absInt(h-expH) > 2)
			if mismatched &&
				nowMs()-lastReassert > 600 && reassert != nil {
				lastReassert = nowMs()
				heal = reassert
			}
			if !mismatched {
				lastStreamMs = nowMs()
				pending = &pend{b64: msg.Params.Data, w: w, h: h}
				cond.Signal()
			}
			mu.Unlock()
			if heal != nil {
				heal() // 锁外发 CDP（conn 自带写锁），避免网络 IO 占着状态锁
			}
		}
	}()
	probeInterval, probeTimeout := rendererProbeInterval, rendererProbeTimeout
	go func() {
		tick := time.NewTicker(probeInterval)
		defer tick.Stop()
		for {
			select {
			case <-watchDone:
				return
			case <-tick.C:
			}
			mu.Lock()
			if closed {
				mu.Unlock()
				return
			}
			unresponsive := probeID != 0 && time.Since(probeAt) >= probeTimeout
			if probeID == 0 {
				probeID = conn.sendID("Runtime.evaluate", map[string]any{"expression": "document.readyState", "returnByValue": true})
				probeAt = time.Now()
			}
			mu.Unlock()
			if unresponsive {
				_ = sink.writeText(map[string]any{"type": "error", "msg": "BROWSER_PAGE_UNRESPONSIVE"})
				shutdown()
				return
			}
		}
	}()

	// 服务端 → 前端：sink.awaitSlot() 决定何时可发（WS 有信用/DC 水位够）；解码放到发送时刻
	// （被丢弃的帧不白解）。帧序号由 sink 分配（与其内部背压/ack 记账对齐）。
	go func() {
		for {
			mu.Lock()
			for pending == nil && !closed {
				cond.Wait()
			}
			if closed {
				mu.Unlock()
				return
			}
			mu.Unlock()

			seq, ok := sink.awaitSlot()
			if sink.closed() {
				return
			}
			if !ok {
				continue // 背压：本轮丢帧（DC 水位过高），不解码不发送
			}
			mu.Lock()
			p := pending
			pending = nil
			mu.Unlock()

			raw, derr := base64.StdEncoding.DecodeString(p.b64)
			if derr != nil {
				continue // 解码失败：跳过（sink 侧信用未占用，见各 sink awaitSlot 语义）
			}
			if sink.writeBinary(buildFrame(raw, p.w, p.h, seq)) != nil {
				shutdown()
				return
			}
		}
	}()

	// 初始档位标签（自适应显示实时档名，手动显示「手动」）
	if auto {
		_ = sink.writeText(map[string]any{"type": "level", "q": ladder[level].q, "name": ladder[level].name})
	} else {
		_ = sink.writeText(map[string]any{"type": "level", "q": cur.q, "name": cur.name})
	}

	// 自适应控制环：按 deliveryMs 升降档。常驻运行，每拍读 auto 决定是否调档——
	// 因为「切画质」不再重连(见下方 emulate/quality 消息)，auto 是运行时可切换的共享态，
	// 不能像以前那样靠「连接时 auto 与否」一次性决定要不要起这个 goroutine。
	go func() {
		t := time.NewTicker(1500 * time.Millisecond)
		defer t.Stop()
		up := 0
		for {
			<-t.C
			mu.Lock()
			if closed {
				mu.Unlock()
				return
			}
			if !auto { // 手动模式：不调档，清掉累计的升档计数
				up = 0
				mu.Unlock()
				continue
			}
			e := ewma
			lv := level
			mu.Unlock()
			if e == 0 {
				continue // 还没有测量样本
			}
			next := lv
			switch {
			case e > 350 && lv > 0: // 帧到达太慢 → 立刻降档保跟手
				next = lv - 1
				up = 0
			case e < 130 && lv < len(ladder)-1: // 有余量 → 连续两次才升档（防抖）
				up++
				if up >= 2 {
					next = lv + 1
					up = 0
				}
			default:
				up = 0
			}
			if next != lv {
				mu.Lock()
				changed := auto // 二次确认仍在自适应（期间可能被切成手动）
				if changed {
					level = next
					ewma = 0 // 换档后重新测量
				}
				mu.Unlock()
				if changed {
					applyLevel(ladder[next])
					_ = sink.writeText(map[string]any{"type": "level", "q": ladder[next].q, "name": ladder[next].name})
				}
			}
		}
	}()

	// 入站控制消息处理：ping/ack/nav/emulate/quality + control 模式下的鼠标/键盘/复制/粘贴。
	// WS 由自身读循环喂、DC 由 OnMessage 喂；逻辑同一份。
	handleCtrl := func(data []byte) {
		var ev struct {
			Type      string  `json:"type"`
			Sub       string  `json:"sub"`
			X         float64 `json:"x"`
			Y         float64 `json:"y"`
			Button    string  `json:"button"`
			Buttons   int     `json:"buttons"` // 当前按下的鼠标键位掩码(1=左)，move 带上才算拖动
			X1        float64 `json:"x1"`      // select：拖动起点（页面 CSS 坐标）
			Y1        float64 `json:"y1"`
			X2        float64 `json:"x2"` // select：拖动当前点/终点
			Y2        float64 `json:"y2"`
			DeltaX    float64 `json:"deltaX"`
			DeltaY    float64 `json:"deltaY"`
			Key       string  `json:"key"`
			Text      string  `json:"text"`
			Modifiers int     `json:"modifiers"`
			URL       string  `json:"url"`
			T         float64 `json:"t"`
			N         uint16  `json:"n"`      // ack 的帧序号
			Mobile    bool    `json:"mobile"` // emulate：true=手机模式
			MW        int     `json:"mw"`     // 移动视口宽（CSS px）
			MH        int     `json:"mh"`     // 移动视口高
			DPR       float64 `json:"dpr"`    // 设备像素比
			UA        string  `json:"ua"`     // 移动 UA
			Auto      bool    `json:"auto"`   // quality：true=自适应
			Q         int     `json:"q"`      // quality：手动 JPEG 质量(10~100)
		}
		if json.Unmarshal(data, &ev) != nil {
			return
		}
		switch ev.Type {
		case "ping": // 测延迟：原样回带客户端时间戳
			_ = sink.writeText(map[string]any{"type": "pong", "t": ev.T})
			return
		case "ack": // 归还信用（sink 内） + 记 deliveryMs 供自适应
			if d, matched := sink.onAck(ev.N); matched {
				mu.Lock()
				if ewma == 0 {
					ewma = d
				} else {
					ewma = ewma*0.7 + d*0.3
				}
				mu.Unlock()
			}
			return
		case "nav":
			if ev.URL != "" {
				conn.send("Page.navigate", map[string]any{"url": ev.URL})
				scheduleForceFrame()
			}
			return
		case "refresh":
			scheduleForceFrame()
			return
		case "emulate": // 设备切换：同一会话现场 set/clear，不重连 → 无泄漏/无竞态
			// 机型/UA 真变了才 reload（让 UA 嗅探站点切移动/桌面版）；纯尺寸变化(桌面 resize)不 reload
			needReload := ev.Mobile != prevMobile || ev.UA != prevUA
			if ev.Mobile {
				mw, mh, dpr := ev.MW, ev.MH, ev.DPR
				if mw == 0 {
					mw = 390
				}
				if mh == 0 {
					mh = 844
				}
				if dpr == 0 {
					dpr = 3
				}
				applyMobile(mw, mh, dpr, ev.UA)
				overrideOn = true
			} else { // 桌面：按观看端原生尺寸覆盖视口（mw/mh<=0 则彻底清除覆盖）
				dpr := ev.DPR
				if dpr == 0 {
					dpr = 1
				}
				applyDesktop(ev.MW, ev.MH, dpr)
				overrideOn = ev.MW > 0 && ev.MH > 0
			}
			prevMobile, prevUA = ev.Mobile, ev.UA
			if needReload { // UA 已先于此设好，reload 的首个请求即带新 UA → 服务端出对应版本
				conn.send("Page.reload", nil)
			}
			scheduleForceFrame()
			return
		case "quality": // 切画质：同一连接现场改档，【不重连】。
			// 重连会重设 device metrics，其后的首帧是「视口还没稳」的畸形帧，object-fit 一
			// letterbox 就是「画面一跳 / 页面忽大忽小」——正是切标清/超清时看到的抖动。改成在
			// 本连接上现场切 startScreencast 参数(只动传输画质/分辨率，不碰视口)即可根除。
			if ev.Auto {
				mu.Lock()
				auto = true
				ewma = 0 // 重新测量，让自适应环从当前链路重新上探
				l := ladder[level]
				mu.Unlock()
				applyLevel(l)
				_ = sink.writeText(map[string]any{"type": "level", "q": l.q, "name": l.name})
			} else {
				q := ev.Q
				if q < 10 {
					q = 10
				} else if q > 100 {
					q = 100
				}
				mu.Lock()
				auto = false
				cur = lvl{q: q, w: 3840, h: 2160, nth: 1, name: "手动"}
				l := cur
				mu.Unlock()
				applyLevel(l)
				_ = sink.writeText(map[string]any{"type": "level", "q": l.q, "name": l.name})
			}
			return
		}
		if !control {
			return
		}
		switch ev.Type {
		case "paste": // 把文本写进远端当前焦点元素（比模拟按键更可靠）
			text := ev.Text
			if text == "" { // 前端没带本机剪贴板文本（读不到/无权限）→ 用浏览器内部剪贴板兜底（内部 Ctrl+C 存的）
				browserClip.mu.Lock()
				text = browserClip.text
				browserClip.mu.Unlock()
			}
			if text != "" {
				conn.send("Input.insertText", map[string]any{"text": text})
				scheduleForceFrame()
			}
		case "copy": // 浏览器 → 本地：取远端页面当前选区文本，回包后前端写进本机剪贴板
			id := conn.sendID("Runtime.evaluate", map[string]any{
				// 取页面当前选区：① window 选区(选正文，最常见) ② 焦点 input/textarea 选区
				// ③ 兜底扫描所有 input/textarea——表单控件选区不进 window.getSelection，且失焦后
				//    selectionStart/End 仍留在元素上，故按元素扫描比依赖 activeElement 当前聚焦更稳。
				"expression": `(function(){var s=window.getSelection().toString();if(s)return s;` +
					`function pick(a){return a&&(a.tagName==='INPUT'||a.tagName==='TEXTAREA')&&a.selectionStart!=null&&a.selectionEnd>a.selectionStart?a.value.substring(a.selectionStart,a.selectionEnd):'';}` +
					`var r=pick(document.activeElement);if(r)return r;` +
					`var els=document.querySelectorAll('input,textarea');` +
					`for(var i=0;i<els.length;i++){r=pick(els[i]);if(r)return r;}return '';})()`,
				"returnByValue": true,
			})
			mu.Lock()
			copyReqID = id
			mu.Unlock()
		case "mouse":
			t := map[string]string{"down": "mousePressed", "up": "mouseReleased", "move": "mouseMoved"}[ev.Sub]
			if t == "" {
				return
			}
			hideCursorForUser()
			p := map[string]any{"type": t, "x": ev.X, "y": ev.Y, "modifiers": ev.Modifiers}
			if ev.Sub != "move" {
				btn := ev.Button
				if btn == "" {
					btn = "left"
				}
				p["button"] = btn
				if ev.Sub == "down" {
					// 500ms 内、24px 半径内、同键位 → 算一次连击；否则重新起算连击数。
					now := nowMs()
					if clickStreak > 0 && btn == lastClickBtn && now-lastClickAt <= 500 &&
						absFloat(ev.X-lastClickX) <= 24 && absFloat(ev.Y-lastClickY) <= 24 {
						clickStreak++
					} else {
						clickStreak = 1
					}
					lastClickAt, lastClickX, lastClickY, lastClickBtn = now, ev.X, ev.Y, btn
					p["buttons"] = 1
				} else { // up：松开时键位掩码归零，clickCount 沿用本次按下时定的连击数
					p["buttons"] = 0
				}
				p["clickCount"] = clickStreak
			} else {
				// 移动时带住按下的键位（1=左键），否则 Chrome 当成悬停 → 拖滑块/画布/拖拽都失效
				p["buttons"] = ev.Buttons
			}
			conn.send("Input.dispatchMouseEvent", p)
			if ev.Sub != "move" {
				scheduleForceFrame()
			}
		case "select": // 拖动框选：headless 下合成鼠标拖选无效，改用 caretRangeFromPoint 按起止坐标在远端建 Range
			conn.send("Runtime.evaluate", map[string]any{
				"expression": fmt.Sprintf(`(function(x1,y1,x2,y2){var s=window.getSelection();s.removeAllRanges();`+
					`var a=document.caretRangeFromPoint(x1,y1),b=document.caretRangeFromPoint(x2,y2);if(!a||!b)return;`+
					`var r=document.createRange();r.setStart(a.startContainer,a.startOffset);r.setEnd(b.startContainer,b.startOffset);`+
					`if(r.collapsed){r.setStart(b.startContainer,b.startOffset);r.setEnd(a.startContainer,a.startOffset);}`+
					`s.addRange(r);})(%g,%g,%g,%g)`, ev.X1, ev.Y1, ev.X2, ev.Y2),
			})
			scheduleForceFrame()
		case "wheel":
			conn.send("Input.dispatchMouseEvent", map[string]any{
				"type": "mouseWheel", "x": ev.X, "y": ev.Y,
				"deltaX": ev.DeltaX, "deltaY": ev.DeltaY, "modifiers": ev.Modifiers,
			})
			scheduleForceFrame()
		case "key":
			// 可打印字符直接 insertText（最可靠，能写进输入框/contenteditable）
			if ev.Sub == "char" {
				if ev.Text != "" {
					conn.send("Input.insertText", map[string]any{"text": ev.Text})
					scheduleForceFrame()
				}
				return
			}
			// 特殊键（回车/退格/方向键/带修饰键的组合）走 dispatchKeyEvent + 虚拟键码
			typ := "keyDown"
			if ev.Sub == "up" {
				typ = "keyUp"
			}
			code, vk, text := keyInfo(ev.Key)
			p := map[string]any{
				"type": typ, "key": ev.Key, "code": code,
				"windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk,
				"modifiers": ev.Modifiers,
			}
			if text != "" {
				p["text"] = text
			}
			conn.send("Input.dispatchKeyEvent", p)
			if ev.Sub == "up" {
				scheduleForceFrame()
			}
		}
	}

	sink.onCtrl(handleCtrl)
	// 生命周期：阻塞到 sink 关闭（WS 读循环退出 / DC 关闭），随后 defer 清视口覆盖 + 关 CDP。
	sink.wait()
	shutdown()
}

func orDefaultInt(v, d int) int {
	if v == 0 {
		return d
	}
	return v
}

func orDefaultFloat(v, d float64) float64 {
	if v == 0 {
		return d
	}
	return v
}
