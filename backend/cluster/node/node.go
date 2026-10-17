// Package node 是标准节点的出站隧道客户端：拨号中心、注册 / 重连、把 Hub
// 转发进来的业务请求交给本机业务 Handler、并定期上报心跳。对现有业务 handler 零改动
// ——只是把「本机 loopback」换成「隧道」。见 docs/design/cluster/architecture.html §1。
package node

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"runtime"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/backend/auth"
	"github.com/ybz21/Roami/backend/cluster/tunnel"
)

// 与 broker 侧约定的接入头（见 cluster/broker/broker.go）。
const (
	hdrEnroll = "X-Roami-Enroll"
	hdrNodeID = "X-Roami-Node-Id"
	hdrToken  = "X-Roami-Node-Token"
	hdrName   = "X-Roami-Node-Name"
	hdrGroup  = "X-Roami-Node-Group"
	hdrMeta   = "X-Roami-Node-Meta"
)

// Client 是节点侧隧道客户端。
type Client struct {
	Hub      string       // 中心地址，如 https://hub.example.com
	Token    string       // 一次性 enrollment token（首次注册用）
	Name     string       // 节点显示名
	Group    string       // 分组
	Insecure bool         // 跳过中心 TLS 校验（自签调试）
	Version  string       // 本机 Roami 版本
	CredPath string       // node.json 落盘路径
	Handler  http.Handler // 本机业务 Handler（server.New 返回的引擎）
	// Stats 供心跳上报本机会话数与负载；为 nil 时报 0。由 main 注入，
	// 免得 cluster/node 反过来依赖 ttmux。
	Stats func() (sessions int, load float64)

	mu    sync.Mutex
	state State
}

// State 是设置页要显示的东西：连上了没、什么时候连上的、上次为什么没连上。
// **「上次失败原因」必须能进界面**——令牌过期 / 凭证失效 / 地址不是中心，
// 三种的下一步完全不同，只写进日志等于让用户自己去翻 journalctl。
type State struct {
	Connected bool      `json:"connected"`
	NodeID    string    `json:"nodeId,omitempty"`
	Since     time.Time `json:"since,omitempty"`
	LastError string    `json:"lastError,omitempty"`
	Retrying  bool      `json:"retrying"`
}

// Status 返回当前接入状态的快照。
func (cl *Client) Status() State {
	cl.mu.Lock()
	defer cl.mu.Unlock()
	return cl.state
}

func (cl *Client) setState(f func(*State)) {
	cl.mu.Lock()
	f(&cl.state)
	cl.mu.Unlock()
}

func (cl *Client) meta() map[string]any {
	host, _ := os.Hostname()
	return map[string]any{
		"hostname":     host,
		"os":           runtime.GOOS,
		"version":      cl.Version,
		"capabilities": []string{"term", "files", "git", "browser", "phone", "swarm"},
	}
}

// Run 持续维持到 中心的隧道：断线指数退避重连，直到 ctx 取消。
func (cl *Client) Run(ctx context.Context) {
	backoff := time.Second
	for {
		if ctx.Err() != nil {
			return
		}
		if err := cl.connectOnce(ctx); err != nil {
			log.Printf("[cluster] 连接 中心 失败: %v（%s 后重试）", err, backoff)
			cl.setState(func(st *State) {
				st.Connected, st.Retrying, st.LastError = false, true, err.Error()
			})
		} else {
			cl.setState(func(st *State) { st.Connected, st.Retrying = false, true })
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
}

// connectOnce 建立一次隧道并服务，直到会话断开才返回。
func (cl *Client) connectOnce(ctx context.Context) error {
	u, err := url.Parse(cl.Hub)
	if err != nil {
		return err
	}
	switch u.Scheme {
	case "https", "wss":
		u.Scheme = "wss"
	default:
		u.Scheme = "ws"
	}
	u.Path = "/cluster/tunnel"

	metaJSON, _ := json.Marshal(cl.meta())
	header := http.Header{}
	header.Set(hdrMeta, string(metaJSON))
	if cl.Name != "" {
		header.Set(hdrName, cl.Name)
	}
	if cl.Group != "" {
		header.Set(hdrGroup, cl.Group)
	}
	creds, _ := loadCreds(cl.CredPath)
	enrolling := creds == nil
	if enrolling {
		if cl.Token == "" {
			return errNoToken
		}
		header.Set(hdrEnroll, cl.Token)
	} else {
		header.Set(hdrNodeID, creds.ID)
		header.Set(hdrToken, creds.Token)
	}

	d := websocket.Dialer{HandshakeTimeout: 15 * time.Second}
	if cl.Insecure {
		d.TLSClientConfig = &tls.Config{InsecureSkipVerify: true} // #nosec G402 —— 仅自签调试
	}
	ws, resp, err := d.Dial(u.String(), header)
	if err != nil {
		// gorilla 在非 101 时只给一句 "websocket: bad handshake"，看不出到底是令牌无效、
		// 节点被移除还是地址写错——而这三种的处理完全不同。把 中心的状态码与错误码带出来。
		// 踩过一次：改口令重启了 中心，内存里的接入令牌全没了，节点这边只有 bad handshake。
		if resp != nil {
			body, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
			_ = resp.Body.Close()
			return fmt.Errorf("%w（中心返回 %s%s）", err, resp.Status, hubHint(resp.StatusCode, string(body)))
		}
		return err
	}
	if enrolling && resp != nil {
		// 注册成功：从 101 响应头取长期节点凭证并落盘，之后用它重连。
		id, tok := resp.Header.Get(hdrNodeID), resp.Header.Get(hdrToken)
		if id != "" && tok != "" {
			if err := saveCreds(cl.CredPath, &creds2{ID: id, Token: tok}); err != nil {
				log.Printf("[cluster] 保存节点凭证失败: %v", err)
			}
			log.Printf("[cluster] 已注册为节点 %s", id)
		}
	}

	sess, err := tunnel.Client(ws)
	if err != nil {
		_ = ws.Close()
		return err
	}
	defer sess.Close()
	log.Printf("[cluster] 已连上 中心 %s", cl.Hub)
	cl.setState(func(st *State) {
		st.Connected, st.Retrying, st.LastError = true, false, ""
		st.Since = time.Now()
		if c, _ := loadCreds(cl.CredPath); c != nil {
			st.NodeID = c.ID
		}
	})
	defer cl.setState(func(st *State) { st.Connected = false })

	go cl.heartbeat(ctx, sess)

	// 中心主动 Open 的流是转发进来的前端业务请求；用本机业务 Handler 服务它们。
	// 隧道流已由 中心完成用户会话校验，标记为内部主体（进程内、不可伪造）后放行本地鉴权。
	internal := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		cl.Handler.ServeHTTP(w, auth.WithInternal(r))
	})
	return http.Serve(sess, internal) // 会话断开即返回
}

// heartbeat 开一条控制流，定期上报换行分隔的心跳 JSON。
// heartbeat 开一条控制流，双向跑：定期上报心跳，并原样回 中心的 ping。
//
// 回声必须和心跳共用**同一条**流——RTT 要量的是这条隧道的往返，另开一条量出来的是别的东西。
// 一条流上两个 goroutine 会撞写，所以写都收口到 send()。
func (cl *Client) heartbeat(ctx context.Context, sess sessionOpener) {
	st, err := sess.Open()
	if err != nil {
		return
	}
	defer st.Close()

	var wmu sync.Mutex
	enc := json.NewEncoder(st)
	send := func(v any) error {
		wmu.Lock()
		defer wmu.Unlock()
		return enc.Encode(v)
	}

	// 回声：读 中心的 {"ping":n}，原样回 {"pong":n}
	go func() {
		sc := bufio.NewScanner(st)
		for sc.Scan() {
			var m struct {
				Ping int64 `json:"ping"`
			}
			if json.Unmarshal(sc.Bytes(), &m) == nil && m.Ping > 0 {
				if send(map[string]any{"pong": m.Ping}) != nil {
					return
				}
			}
		}
	}()

	t := time.NewTicker(15 * time.Second)
	defer t.Stop()
	for {
		n, load := 0, 0.0
		if cl.Stats != nil {
			n, load = cl.Stats()
		}
		if err := send(map[string]any{"heartbeat": true, "sessionCount": n, "load": load}); err != nil {
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-t.C:
		}
	}
}

// hubHint 把 中心的错误码翻成「下一步该干什么」。接入失败最常见的两种原因
// （令牌无效 / 凭证失效）都要人去控制台重新签一次，光有状态码不够。
func hubHint(code int, body string) string {
	switch {
	case strings.Contains(body, "ENROLL_INVALID"):
		return "：接入令牌无效或已过期，去控制台「添加机器」重新签一个"
	case strings.Contains(body, "NODE_UNAUTHORIZED"):
		return "：节点凭证已失效（可能被移除过），删掉 <home>/cluster/node.json 后用新令牌重新接入"
	case code == 404:
		return "：这个地址上没有 中心（对方是普通 Roami？检查 cluster.broker）"
	case code == 401 || code == 403:
		return "：被拒绝，检查令牌"
	}
	if body != "" {
		return "：" + strings.TrimSpace(body)
	}
	return ""
}
