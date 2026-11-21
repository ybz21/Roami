// link.go：Phase 1a 会话级常驻 control PeerConnection + DuplexTransport 分派骨架。
//
// 与「每下载一个 file PC」（manager.go/transfer.go）不同，link 是**按 (WS 会话, class) 建的
// 持久 PC**：不随单次 transfer 拆，随 WS 生命周期存活（WS 断→closeAll→link.close）。
//
// 本阶段范围（见 general-transport-plan.md §1/§2/§3）：
//   - control（Phase 1a）与 media（Phase 1b：浏览器镜像）两类持久 PC；file 仍走每传输一个。
//   - DuplexTransport 分派骨架：control PC 的 OnDataChannel 按 label 前缀分派到 handler。
//     本阶段实现一个 echo 服务（label 前缀 "echo"）：收到任何 message 原样回发
//     （text 回 text、binary 回 binary），用于证明双向通道通。
//   - 链路状态事件：Connected→classifyPath（复用 manager.go）→ 发 {type:"link",
//     class,state:"up",path,local,remote,rttMs}；断开/失败发 {type:"link",class,state:"down"}。
//
// 复用现有 SettingEngine(ice.go)/鉴权(g 组 cookie)/灰度(ROAM_WEB_P2P_ENABLE)——link PC
// 与 file PC 共用同一份 hub.api / hub.rtcConfig，各自独立 SCTP association（拥塞隔离）。
package p2p

import (
	"log"
	"strings"

	"github.com/pion/webrtc/v4"
)

// dispatcher 把一条 DataChannel 按 label 前缀分派到对应 handler（DuplexTransport 骨架）。
// 每个 handler 只见 send/recv/close，不感知底层是 P2P 还是 frp（§2）。
// 本阶段只注册 echo，一个前缀对应一个 handler。
type dcHandler func(dc *webrtc.DataChannel)

// linkHandlers 是 label 前缀 → handler 的分派表。后续阶段（term/…）在此扩展。
//
//   - "echo"：Phase 1a 双向通道自测。
var linkHandlers = map[string]dcHandler{
	"echo": serveEcho,
	// "bytes"：浏览器要某个文件的某一段（图片/视频/PDF 的 Range 请求，见 bytes.go）。
	// 开在常驻 PC 上——拖一次进度条就是一次新请求，不能每次重新打洞。
	"bytes": serveBytes,
}

// dispatchDataChannel 按 label 前缀查表分派；未匹配的 label 直接关闭该通道。
func dispatchDataChannel(dc *webrtc.DataChannel) {
	label := dc.Label()
	for prefix, h := range linkHandlers {
		if strings.HasPrefix(label, prefix) {
			h(dc)
			return
		}
	}
	log.Printf("p2p: link dc label=%q no handler, closing", label)
	_ = dc.Close()
}

// isLinkClass 判定一个信令 class 是否走持久 link PC。
//   - control：终端 I/O / REST / 剪贴板（可靠·有序，Phase 1a）。
//   - media：浏览器镜像 / 手机镜像（不可靠·无序，独立 SCTP 与 control 隔离，Phase 1b 起）。
//
// media PC 与 control 同法建（会话级持久、复用 SettingEngine/classifyPath/link 事件），
// 差异只在承载的 DataChannel 通道语义由前端 createDataChannel 决定（media 用
// ordered:false,maxRetransmits:0），后端 OnDataChannel 拿到即是该配置，无需后端区分。
func isLinkClass(class string) bool {
	return class == "control" || class == "media"
}

// link 是一条会话级常驻 PeerConnection（按 class 建，不随 transfer 拆）。
// 建链/answer/ice/状态回调全走共享底层 peer（pc.go），link 只保留「持久生命周期 + class 语义」。
type link struct {
	class string
	*peer // 共享底层 PC（建链/answer/ice/classifyPath 唯一实现）
}

// getLink / putLink 维护 class → *link 表。
func (s *session) getLink(class string) *link {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.links[class]
}

// onLinkSignal 分发持久 link PC 的信令（offer/ice/cancel）。
func (s *session) onLinkSignal(m SignalMsg) {
	switch m.Type {
	case "offer":
		s.startLink(m)
	case "ice":
		s.addLinkICE(m)
	case "cancel", "fallback":
		s.finishLink(m.Class)
	}
}

// addLinkICE 转发 trickle ICE 候选给对应 class 的持久 PC（走共享底层，含远端候选诊断日志）。
func (s *session) addLinkICE(m SignalMsg) {
	l := s.getLink(m.Class)
	if l == nil {
		return
	}
	s.addRemoteICE(l.peer, linkPeerConfig(m.Class), m.Candidate)
}

// linkPeerConfig 构造持久 link PC 的底层参数：按 class 定位、逐条打印候选、Disconnected 也算断开。
// onConnected/onDown 在 startLink 里补齐（需捕获具体 *link）。
func linkPeerConfig(class string) peerConfig {
	return peerConfig{
		keyLog:             "link=" + class,
		signalKey:          class,
		byClass:            true,
		verboseCand:        true,
		downOnDisconnected: true,
		onDataChannel:      dispatchDataChannel,
	}
}

// candStr 把候选诊断信息压成一行 typ@addr（nil 时给占位）。
func candStr(c *CandInfo) string {
	if c == nil {
		return "?"
	}
	return c.Type + "@" + c.Addr
}

// parseCandStr 从 SDP 候选串里抽出 (typ, addr)，仅用于日志，best-effort。
// 形如 "candidate:foundation 1 udp 1234 1.2.3.4 5678 typ srflx raddr ..."：
// 字段 4 是连接地址，"typ" 后一字段是候选类型。
func parseCandStr(cand string) (typ, addr string) {
	f := strings.Fields(cand)
	if len(f) < 6 {
		return "", ""
	}
	addr = f[4]
	for i := 0; i+1 < len(f); i++ {
		if f[i] == "typ" {
			typ = f[i+1]
			break
		}
	}
	return typ, addr
}

// finishLink 终结并移除一个 class 的持久 PC，并向前端发 link down。幂等。
func (s *session) finishLink(class string) {
	s.mu.Lock()
	l := s.links[class]
	delete(s.links, class)
	s.mu.Unlock()
	if l == nil {
		return
	}
	l.close()
	_ = s.send(SignalMsg{Type: "link", Class: class, State: "down"})
}

// startLink 建会话级常驻 PC、设远端 SDP、回 answer，并挂好回调（trickle ICE / 状态 / 分派）。
//
// 每 (WS 会话, class) 只有一条：重复 offer 直接忽略（前端应对已存在的 link 复用，不再 offer）。
func (s *session) startLink(m SignalMsg) {
	if s.getLink(m.Class) != nil {
		return // 已有该 class 的持久 PC，忽略重复 offer
	}
	class := m.Class
	cfg := linkPeerConfig(class)
	// Connected/断开回调需捕获 class，向前端发 link up/down（线协议与收敛前一致）。
	cfg.onConnected = func(path string, local, remote *CandInfo, rtt int) {
		log.Printf("p2p: link=%s connected path=%s pair local=%s remote=%s rttMs=%d",
			class, path, candStr(local), candStr(remote), rtt)
		_ = s.send(SignalMsg{
			Type:   "link",
			Class:  class,
			State:  "up",
			Path:   path,
			Local:  local,
			Remote: remote,
			RTTMs:  rtt,
		})
	}
	cfg.onDown = func() { s.finishLink(class) }

	p, err := s.newPeer(cfg)
	if err != nil {
		log.Printf("p2p: link=%s NewPeerConnection: %v", class, err)
		return
	}
	l := &link{class: class, peer: p}

	s.mu.Lock()
	// 双检：并发 offer 竞态下只保留先入者。
	if _, exists := s.links[class]; exists {
		s.mu.Unlock()
		p.close()
		return
	}
	s.links[class] = l
	s.mu.Unlock()

	// 非 trickle：answerOffer 会等 ICE gathering 完成后再回携带全部候选的完整 answer SDP，
	// 可能阻塞数秒。放到 goroutine 里执行，避免卡住信令 WS 读循环（不再需要 trickle ICE 消息）。
	go func() {
		if err := s.answerOffer(p, cfg, m.SDP); err != nil {
			s.finishLink(class)
		}
	}()
}

// serveEcho 是 DuplexTransport 分派骨架的验证 handler（label 前缀 "echo"）：
// 收到任何 message 原样回发（text 回 text，binary 回 binary）。证明双向通道通。
func serveEcho(dc *webrtc.DataChannel) {
	label := dc.Label()
	dc.OnOpen(func() {
		log.Printf("p2p: echo dc label=%q open", label)
	})
	dc.OnMessage(func(msg webrtc.DataChannelMessage) {
		if msg.IsString {
			if err := dc.SendText(string(msg.Data)); err != nil {
				log.Printf("p2p: echo dc label=%q SendText: %v", label, err)
			}
			return
		}
		if err := dc.Send(msg.Data); err != nil {
			log.Printf("p2p: echo dc label=%q Send: %v", label, err)
		}
	})
	dc.OnClose(func() {
		log.Printf("p2p: echo dc label=%q close", label)
	})
}
