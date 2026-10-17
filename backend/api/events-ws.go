package api

import (
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
)

// EventHub 把会话事件（等你 / 做完 / 出错）实时推给长连接客户端。
// Android App 就靠这条：它跑在 WebView 里收不到 Web Push，只能自己前台服务挂一条 WebSocket
// （Gotify / ntfy 的做法），事件来了自己弹本地通知。和 Web Push、收件箱是同一份事件。
type EventHub struct {
	mu   sync.Mutex
	subs map[chan PushPayload]struct{}
}

func (h *EventHub) subscribe() chan PushPayload {
	ch := make(chan PushPayload, 32)
	h.mu.Lock()
	if h.subs == nil {
		h.subs = map[chan PushPayload]struct{}{}
	}
	h.subs[ch] = struct{}{}
	h.mu.Unlock()
	return ch
}

func (h *EventHub) unsubscribe(ch chan PushPayload) {
	h.mu.Lock()
	delete(h.subs, ch)
	h.mu.Unlock()
}

// Count 当前挂着的长连接数
func (h *EventHub) Count() int {
	h.mu.Lock()
	defer h.mu.Unlock()
	return len(h.subs)
}

// Broadcast 不阻塞：客户端读得慢就丢它这条，别拖住探测循环
func (h *EventHub) Broadcast(p PushPayload) { h.enqueue(p) }

func (h *EventHub) enqueue(p PushPayload) (accepted, dropped int) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for ch := range h.subs {
		select {
		case ch <- p:
			accepted++
		default:
			dropped++
		}
	}
	return
}

var eventsUpgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 4096,
	CheckOrigin: func(r *http.Request) bool {
		origin := r.Header.Get("Origin")
		if origin == "" {
			return true // App / 非浏览器客户端
		}
		i := strings.Index(origin, "://")
		return i >= 0 && origin[i+3:] == r.Host
	},
}

// EventsWS GET /api/events/ws —— 每条事件一帧 JSON（PushPayload），30s 一个 ping 保活
func (a *API) EventsWS(c *gin.Context) {
	conn, err := eventsUpgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer conn.Close()
	ch := a.Events.subscribe()
	defer a.Events.unsubscribe(ch)
	_ = conn.WriteJSON(gin.H{"type": "hello", "badge": a.Inbox.Unread()})
	done := make(chan struct{})
	go func() { // 只为发现对端断开；客户端不需要发任何东西
		defer close(done)
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}()
	ping := time.NewTicker(30 * time.Second)
	defer ping.Stop()
	for {
		select {
		case <-done:
			return
		case p := <-ch:
			_ = conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := conn.WriteJSON(p); err != nil {
				return
			}
		case <-ping.C:
			_ = conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
			if err := conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}
