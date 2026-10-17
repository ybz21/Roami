// Package stream 提供实时通道：
//
//	Status — SSE，定期推送 tasks + sessions 快照（前端免轮询）
//	Logs   — WebSocket，tail -f 指定会话日志
package stream

import (
	"bufio"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/backend/ttmux"
)

type Hub struct {
	tt      *ttmux.Client
	logsDir string
}

func New(tt *ttmux.Client, logsDir string) *Hub { return &Hub{tt: tt, logsDir: logsDir} }

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		origin := r.Header.Get("Origin")
		if origin == "" {
			return true
		}
		i := strings.Index(origin, "://")
		return i >= 0 && origin[i+3:] == r.Host
	},
}

func writeSSE(c *gin.Context, event, data string) {
	if event != "" {
		io.WriteString(c.Writer, "event: "+event+"\n")
	}
	// 多行数据按 SSE 规范拆成多条 data: 行，客户端会以 \n 重新拼接
	for _, line := range strings.Split(data, "\n") {
		io.WriteString(c.Writer, "data: "+line+"\n")
	}
	io.WriteString(c.Writer, "\n")
}

// Status SSE：每 2s 推送 {"tasks":[...],"sessions":[...]}
func (h *Hub) Status(c *gin.Context) {
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("Connection", "keep-alive")
	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		c.Status(http.StatusInternalServerError)
		return
	}

	send := func() {
		groups, _ := h.tt.Run("group", "ls", "--json")
		sess, _ := h.tt.Run("ls", "--json")
		payload := `{"tasks":` + strings.TrimSpace(groups) + `,"sessions":` + strings.TrimSpace(sess) + `}`
		writeSSE(c, "status", payload)
		flusher.Flush()
	}

	send()
	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-c.Request.Context().Done():
			return
		case <-ticker.C:
			send()
		}
	}
}

// Logs WebSocket：tail -f 指定会话日志
func (h *Hub) Logs(c *gin.Context) {
	name := c.Param("name")
	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer conn.Close()

	path := filepath.Join(h.logsDir, name+".log")
	f, err := os.Open(path)
	if err != nil {
		conn.WriteMessage(websocket.TextMessage, []byte("[无日志: "+name+"]"))
		return
	}
	defer f.Close()

	// 读取端用于探测客户端断开
	closed := make(chan struct{})
	go func() {
		for {
			if _, _, e := conn.ReadMessage(); e != nil {
				close(closed)
				return
			}
		}
	}()

	reader := bufio.NewReader(f)
	for {
		select {
		case <-closed:
			return
		default:
		}
		line, err := reader.ReadString('\n')
		if len(line) > 0 {
			if conn.WriteMessage(websocket.TextMessage, []byte(line)) != nil {
				return
			}
		}
		if err == io.EOF {
			time.Sleep(400 * time.Millisecond)
		} else if err != nil {
			return
		}
	}
}
