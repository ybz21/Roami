// screencast_dc.go：镜像传输的 WebRTC DataChannel sink（media PC，Phase 1b）。
//
// 与 wsSink 的关键差异 = 通道语义不同，故背压策略不同：
//
//   - 通道是【不可靠·无序】（前端 createDataChannel(ordered:false,maxRetransmits:0)，
//     后端 OnDataChannel 拿到的就是该配置）——丢帧优于阻塞，天然适配镜像。
//   - 背压改用 dc.BufferedAmount()：超高水位就【跳过当前帧】（awaitSlot 返回 ok=false），
//     绝不像 WS 那样靠信用死等 ack。这样慢链路自动丢中间帧，不在 SCTP 发送缓冲里堆积。
//   - 控制消息（ack/ping/level/质量调节等 JSON）走同一 DataChannel 的 text message：
//     入站文本 → onCtrl 喂回核心；出站 JSON → SendText。
//   - 前端仍会发 {type:'ack',n:seq}（不再用于信用，只喂 deliveryMs 给自适应码率环）。
//
// 帧生产 / 自适应 / CDP 逻辑全在 runScreencast 复用，这里只实现「写帧 + 背压」这层。
package browser

import (
	"encoding/json"
	"log"
	"net/url"
	"strings"
	"sync"

	"github.com/pion/webrtc/v4"
)

// dcHighWater 是 DataChannel 发送缓冲的丢帧水位（字节）。BufferedAmount 超过它，
// awaitSlot 就跳过当前帧——一帧 JPEG 约几十~几百 KB，留 ~1MB 余量约等于个位数帧在途，
// 与 WS window=2 的「限在途帧」意图一致，但不阻塞、不等 ack。
const dcHighWater = 1 << 20 // 1 MiB

// dcSink 用一条 WebRTC DataChannel 承载帧与控制，实现 frameSink。
type dcSink struct {
	dc *webrtc.DataChannel

	mu      sync.Mutex
	seq     uint16
	sentAt  map[uint16]int64
	isClose bool

	ctrl func([]byte)
	done chan struct{} // OnClose 触发后关闭 → wait() 返回
}

func newDCSink(dc *webrtc.DataChannel) *dcSink {
	return &dcSink{
		dc:     dc,
		sentAt: map[uint16]int64{},
		done:   make(chan struct{}),
	}
}

func (s *dcSink) writeBinary(b []byte) error { return s.dc.Send(b) }

func (s *dcSink) writeText(v any) error {
	raw, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return s.dc.SendText(string(raw))
}

func (s *dcSink) onCtrl(fn func([]byte)) { s.ctrl = fn }

func (s *dcSink) closed() bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.isClose
}

func (s *dcSink) close() {
	s.mu.Lock()
	first := !s.isClose
	s.isClose = true
	s.mu.Unlock()
	if first {
		close(s.done)
	}
	_ = s.dc.Close()
}

func (s *dcSink) wait() { <-s.done }

// awaitSlot 背压：不可靠通道不等 ack，只看 BufferedAmount。水位过高就丢当前帧
// （返回 ok=false，核心据此跳过不解码不发）；否则分配 seq、记发出时刻。
func (s *dcSink) awaitSlot() (uint16, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.isClose {
		return 0, false
	}
	if s.dc.BufferedAmount() > dcHighWater {
		return 0, false // 丢帧优于阻塞
	}
	s.seq++
	seq := s.seq
	s.sentAt[seq] = nowMs()
	return seq, true
}

// onAck 只记 deliveryMs（无信用可归还）。
func (s *dcSink) onAck(n uint16) (float64, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if ts, ok := s.sentAt[n]; ok {
		delete(s.sentAt, n)
		return float64(nowMs() - ts), true
	}
	return 0, false
}

// serveScreencastDC 是 media PC 上 label 前缀 "screencast" 的 DataChannel handler。
// 由 p2p 包在 media/control PC 收到该 label 的通道时回调（经 RegisterScreencastHandler 注册）。
//
// 入参（target/control/auto/q/mobile/...）全部编在 DataChannel label 的 query 里
// （前端 createDataChannel(`screencast#<id>?target=..&control=1&..`)），随通道建立可靠送达，
// 由 parseDCOptions 解析。这条通道是【不可靠·无序】的，绝不能把这些一次性关键入参放进业务
// 消息发（会丢包/乱序，实测首帧常是 emulate 抢在握手前到，握手包还可能整包丢失）。
func serveScreencastDC(dc *webrtc.DataChannel) {
	opts := parseDCOptions(dc.Label())
	sink := newDCSink(dc)

	dc.OnMessage(func(msg webrtc.DataChannelMessage) {
		if !msg.IsString { // 控制消息走 text；二进制入站无用途，忽略
			return
		}
		if sink.ctrl != nil { // runScreencast 注册 onCtrl 前的极短窗口内到的消息丢弃（nil 守卫）
			sink.ctrl(msg.Data)
		}
	})
	dc.OnClose(func() {
		log.Printf("p2p: screencast dc label=%q close", dc.Label())
		sink.close()
	})
	dc.OnError(func(err error) {
		log.Printf("p2p: screencast dc label=%q error: %v", dc.Label(), err)
		sink.close()
	})

	// OnOpen：通道就绪后再跑核心（此时 Send 才有意义）。runScreencast 阻塞到 sink 关闭，
	// 故放独立 goroutine，不占 pion 的回调线程。
	dc.OnOpen(func() {
		log.Printf("p2p: screencast dc label=%q open target=%q control=%v auto=%v", dc.Label(), opts.target, opts.control, opts.auto)
		go func() {
			runScreencast(sink, opts)
			sink.close() // 兜底：核心早退（dial 失败等）也关通道，避免半开 DataChannel 泄漏
		}()
	})
}

// parseDCOptions 从 DataChannel label 的 query 部分解析镜像入参。
// label 形如 "screencast#<id>?target=..&control=1&auto=1&mobile=1&mw=..&mh=..&dpr=..&ua=.."。
func parseDCOptions(label string) scOptions {
	opts := scOptions{q: 80, mw: 390, mh: 844, dpr: 3}
	i := strings.IndexByte(label, '?')
	if i < 0 {
		return opts
	}
	q, err := url.ParseQuery(label[i+1:])
	if err != nil {
		return opts
	}
	opts.target = q.Get("target")
	opts.expectedBrowser = q.Get("expectedBrowser")
	opts.control = q.Get("control") == "1"
	opts.auto = q.Get("auto") == "1"
	opts.q = atoiDefault(q.Get("q"), 80)
	opts.mobile = q.Get("mobile") == "1"
	opts.mw = atoiDefault(q.Get("mw"), 390)
	opts.mh = atoiDefault(q.Get("mh"), 844)
	opts.dpr = atofDefault(q.Get("dpr"), 3)
	opts.ua = q.Get("ua")
	return opts
}

// ScreencastDCHandler 供 p2p 包注册进 linkHandlers（label 前缀 "screencast"）。
// 独立导出函数避免 p2p→browser / browser→p2p 的循环 import：由 server 层在启动时
// p2p.RegisterScreencastHandler(browser.ScreencastDCHandler) 完成接线。
func ScreencastDCHandler(dc *webrtc.DataChannel) { serveScreencastDC(dc) }
