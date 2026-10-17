package hub

import (
	"bufio"
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/hashicorp/yamux"
	"github.com/ybz21/Roami/backend/cluster/tunnel"
)

// 中心 组合注册表 + 隧道服务端 + 反代，暴露一组 gin.HandlerFunc。
type Hub struct {
	reg *Registry
	up  websocket.Upgrader

	publicURL string        // 中心的对外地址（config: cluster.public_url）；空 = 按请求 Host 推
	enrollTTL time.Duration // 接入令牌有效期（config: cluster.enroll_ttl_min）

	version string // 注入的构建版本，/api/hub/self 回给控制台
	self    *selfStats

	mu      sync.Mutex
	proxies map[string]*nodeTransport // 每台节点一个复用的 Transport，见 transportFor
}

// nodeTransport 绑在**某一条隧道会话**上：节点重连会换 session，那时旧的必须整个丢掉，
// 否则新请求会打进一条已经死掉的隧道。
type nodeTransport struct {
	sess *yamux.Session
	tr   *http.Transport
}

// SetPublicURL / SetEnrollTTL / SetVersion 由装配处注入，免得 hub 包反过来依赖 config。
func (b *Hub) SetPublicURL(u string)        { b.publicURL = strings.TrimRight(u, "/") }
func (b *Hub) SetVersion(v string)          { b.version = v }
func (b *Hub) SetEnrollTTL(d time.Duration) { b.enrollTTL = d }

// New 从 dir 加载注册表（nodes.json）。
func New(dir string) *Hub {
	return &Hub{
		reg:  NewRegistry(dir),
		self: newSelfStats(),
		// 节点接入靠 token 鉴权（见 HandleTunnel），来源不是浏览器，放开 Origin 校验。
		up: websocket.Upgrader{ReadBufferSize: 4096, WriteBufferSize: 4096, CheckOrigin: func(*http.Request) bool { return true }},
	}
}

// 隧道接入 / 心跳协议里用到的头。
const (
	hdrEnroll = "X-Roami-Enroll"     // 一次性接入令牌（首次注册）
	hdrNodeID = "X-Roami-Node-Id"    // 长期节点 id（重连）
	hdrToken  = "X-Roami-Node-Token" // 长期节点凭证（重连；注册成功时经 101 响应头下发一次）
	hdrName   = "X-Roami-Node-Name"
	hdrGroup  = "X-Roami-Node-Group"
	hdrMeta   = "X-Roami-Node-Meta" // JSON(NodeMeta)
)

// HandleTunnel 是节点出站拨号的落点：先按 token 鉴权（enrollment 或长期凭证），
// 再升级为 WebSocket、包成 yamux 会话并登记。**不走用户会话鉴权**——它是节点在连，
// 不是浏览器。鉴权在 Upgrade 之前完成，避免给未授权连接升级协议。
func (b *Hub) HandleTunnel(c *gin.Context) {
	var meta NodeMeta
	if s := c.GetHeader(hdrMeta); s != "" {
		_ = json.Unmarshal([]byte(s), &meta)
	}

	var id, plainToken string
	respHeader := http.Header{}
	if enroll := c.GetHeader(hdrEnroll); enroll != "" {
		var ok bool
		id, plainToken, ok = b.reg.ConsumeEnrollment(enroll, c.GetHeader(hdrName), c.GetHeader(hdrGroup), meta)
		if !ok {
			c.JSON(http.StatusUnauthorized, gin.H{"error": gin.H{"code": "ENROLL_INVALID"}})
			return
		}
		// 长期凭证经 101 响应头下发一次；节点收到后落盘 node.json，之后用它重连。
		respHeader.Set(hdrNodeID, id)
		respHeader.Set(hdrToken, plainToken)
	} else {
		id = c.GetHeader(hdrNodeID)
		if id == "" || !b.reg.AuthNode(id, c.GetHeader(hdrToken)) {
			c.JSON(http.StatusUnauthorized, gin.H{"error": gin.H{"code": "NODE_UNAUTHORIZED"}})
			return
		}
	}

	ws, err := b.up.Upgrade(c.Writer, c.Request, respHeader)
	if err != nil {
		return // Upgrade 内部已写响应
	}
	sess, err := tunnel.Server(ws)
	if err != nil {
		_ = ws.Close()
		return
	}
	b.reg.Attach(id, sess, meta)
	b.self.nodeUp(b.reg.NameOf(id))
	defer func() {
		b.self.nodeDown(b.reg.NameOf(id))
		b.reg.Detach(id, sess)
		b.dropTransport(id)
		_ = sess.Close()
	}()

	// 节点主动开的流是控制流（心跳）；前端请求走 中心主动 Open 的流（见 proxyNode）。
	for {
		st, err := sess.Accept()
		if err != nil {
			return // 会话断开
		}
		go b.readControl(id, st)
	}
}

// readControl 读一条控制流上换行分隔的心跳 JSON：{"sessionCount":n,"load":f}。
// readControl 读控制流：节点的心跳 JSON 与 ping 的回声，同时反向发 ping 测 RTT。
//
// 心跳是节点**单向上报**，拿不到往返时延，而界面每一处都要显示「12ms」；单向上报还让
// 掉线只能靠超时发现。所以 中心主动在同一条流上发 {"ping":n}，节点原样回 {"pong":n}，
// 用发出时刻算 RTT 的 EWMA。见 architecture.html §3 ③。
func (b *Hub) readControl(id string, conn net.Conn) {
	defer conn.Close()

	var mu sync.Mutex
	sentAt := map[int64]time.Time{}
	stop := make(chan struct{})
	defer close(stop)

	go func() {
		enc := json.NewEncoder(conn)
		t := time.NewTicker(5 * time.Second)
		defer t.Stop()
		for seq := int64(1); ; seq++ {
			mu.Lock()
			sentAt[seq] = time.Now()
			// 只留最近 32 个在途序号，节点若不回 pong 也不会把 map 撑大
			if len(sentAt) > 32 {
				for k := range sentAt {
					if k <= seq-32 {
						delete(sentAt, k)
					}
				}
			}
			mu.Unlock()
			if err := enc.Encode(map[string]any{"ping": seq}); err != nil {
				return
			}
			select {
			case <-stop:
				return
			case <-t.C:
			}
		}
	}()

	sc := bufio.NewScanner(conn)
	for sc.Scan() {
		var msg struct {
			SessionCount int     `json:"sessionCount"`
			Load         float64 `json:"load"`
			Pong         int64   `json:"pong"`
			Heartbeat    bool    `json:"heartbeat"`
		}
		if json.Unmarshal(sc.Bytes(), &msg) != nil {
			continue
		}
		if msg.Pong > 0 {
			mu.Lock()
			at, ok := sentAt[msg.Pong]
			delete(sentAt, msg.Pong)
			mu.Unlock()
			if ok {
				b.reg.Latency(id, time.Since(at))
			}
			continue
		}
		if msg.Heartbeat {
			b.reg.Heartbeat(id, msg.SessionCount, msg.Load)
		}
	}
}

// Nodes 返回节点列表（/api/hub/nodes）。
func (b *Hub) Nodes(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"data": b.reg.List()})
}

// Bootstrap 返回控制台启动所需的最小信息（/api/hub/bootstrap）：可访问节点 +
// 推荐节点。**Hub 本地处理，不依赖 current node**，消除前端 currentNode 启动循环。
// 见 docs/design/cluster/architecture.html §7。
func (b *Hub) Bootstrap(c *gin.Context) {
	nodes := b.reg.List()
	recommended := ""
	for _, n := range nodes {
		if n.Online {
			recommended = n.ID
			break
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"nodes": nodes, "recommended": recommended}})
}

// Enroll 签发一次性接入令牌并给出接入命令（POST /api/hub/enroll）。
// Enroll 签发一次性接入令牌，并把接入命令拼好。
//
// **命令里的地址不能想当然用请求的 Host**：你在局域网里管中心，那就是内网地址，
// 外网那台机器照着这条命令做必然连不上，而它那边只会报「连接失败」，看不出是地址的问题。
// 所以优先用显式配置的对外地址，没配才回落。
func (b *Hub) Enroll(c *gin.Context) {
	var body struct{ Name, Group string }
	_ = c.ShouldBindJSON(&body)
	e := b.reg.CreateEnrollment(body.Name, body.Group, b.enrollTTL)
	base := b.publicURL
	if base == "" {
		base = requestBase(c)
	}
	cmd := "curl -fsSL " + base + "/install.sh | bash -s -- --hub " + base + " --token " + e.Token
	if body.Name != "" {
		cmd += " --name " + strconv.Quote(body.Name)
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"token": e.Token, "expiresAt": e.ExpiresAt, "command": cmd,
		"hubUrl": base, "private": isPrivateURL(base),
	}})
}

func requestBase(c *gin.Context) string {
	scheme := "https"
	if c.Request.TLS == nil && c.GetHeader("X-Forwarded-Proto") != "https" {
		scheme = "http"
	}
	return scheme + "://" + c.Request.Host
}

// isPrivateURL 判断这个地址是不是只在局域网里有效。**纯本地判断，不去探测可达性**——
// 那件事中心自己做不到，而这一条静态判断已经能挡住绝大多数「照着命令做却连不上」。
func isPrivateURL(raw string) bool {
	u, err := url.Parse(raw)
	if err != nil {
		return false
	}
	h := u.Hostname()
	if h == "localhost" || strings.HasSuffix(h, ".local") || strings.HasSuffix(h, ".lan") {
		return true
	}
	ip := net.ParseIP(h)
	if ip == nil {
		return false // 域名：假定是对外的，判不了就别乱报警
	}
	return ip.IsLoopback() || ip.IsPrivate() || ip.IsLinkLocalUnicast()
}

// transportFor 返回该节点**复用**的 Transport。
//
// 这里曾经是每个请求 new 一个 http.Transport——一个真实的 goroutine 泄漏，2026-08-11
// 把中心压死过一次（19185 个 goroutine，其中 9572 对 readLoop/writeLoop 卡在
// yamux.Stream.Read 上，最久的一个挂了 661 分钟；RSS 从 20MB 涨到 300MB，
// 端口能连但不再 accept）。
//
// 机理：Transport 自带空闲连接池。请求结束后那条 yamux 流被放回池里，
// readLoop/writeLoop 继续挂着等数据；手写的 Transport 的 IdleConnTimeout 默认是 0
// （永不超时），而这个 Transport 本身又随请求结束被丢掉，没人再调 CloseIdleConnections()。
// 于是每个经中心代理的请求都留下两个永不退出的 goroutine 和一条永不关闭的流——
// 控制台每 5 秒轮询一次，一夜就是几千个。
//
// 现在按节点缓存并加上超时与上限：空闲流会自己过期回收，池子也不会无限长。
func (b *Hub) transportFor(id string, sess *yamux.Session) *http.Transport {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.proxies == nil {
		b.proxies = map[string]*nodeTransport{}
	}
	if cur := b.proxies[id]; cur != nil {
		if cur.sess == sess {
			return cur.tr
		}
		cur.tr.CloseIdleConnections() // 节点重连了：旧隧道上的流全作废
	}
	tr := &http.Transport{
		DialContext:           func(context.Context, string, string) (net.Conn, error) { return sess.Open() },
		ResponseHeaderTimeout: 30 * time.Second,
		// 空闲的隧道流最多留 90 秒。yamux 流很便宜，宁可多开也不要攒着——
		// 攒着的每一条都是一对活 goroutine。
		IdleConnTimeout:     90 * time.Second,
		MaxIdleConnsPerHost: 8,
	}
	b.proxies[id] = &nodeTransport{sess: sess, tr: tr}
	return tr
}

// dropTransport 在隧道断开时清掉该节点的 Transport 与它池里的流。
func (b *Hub) dropTransport(id string) {
	b.mu.Lock()
	cur := b.proxies[id]
	delete(b.proxies, id)
	b.mu.Unlock()
	if cur != nil {
		cur.tr.CloseIdleConnections()
	}
}

// ProxyNode 把 /n/:nodeId/*path 反代进目标节点的隧道流（REST + WebSocket 升级）。
// 转发本体是 httputil.ReverseProxy（同 backend/browser/devtools.go），只是把底层连接
// 换成该节点隧道上 Open() 出来的 yamux 流。见架构文档 §7.2。
func (b *Hub) ProxyNode(c *gin.Context) {
	b.self.requests.Add(1)
	id := c.Param("nodeId")
	sess := b.reg.Session(id)
	if sess == nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"code": "NODE_OFFLINE"}})
		return
	}
	target := &url.URL{Scheme: "http", Host: "node"}
	rp := httputil.NewSingleHostReverseProxy(target)
	rp.Transport = b.transportFor(id, sess)
	rp.ErrorHandler = func(w http.ResponseWriter, _ *http.Request, _ error) {
		w.WriteHeader(http.StatusBadGateway)
	}
	// 剥掉 /n/<id> 前缀，节点业务 Handler 只认 /api/...。
	//
	// **按前缀截断，不能拿 c.Param("path") 重建**：Param 给的是已解码值，赋回 Path 会让
	// RawPath 失效、转发时按默认规则重新编码。而 /api/file/serve/*path 把绝对路径塞进 URL，
	// 文件名里的 # ? % 空格全会在这一跳变形 → 预览/下载 404。见 architecture.html §3 ①。
	prefix := "/n/" + url.PathEscape(id)
	c.Request.URL.Path = strings.TrimPrefix(c.Request.URL.Path, "/n/"+id)
	if c.Request.URL.RawPath != "" {
		c.Request.URL.RawPath = strings.TrimPrefix(c.Request.URL.RawPath, prefix)
	}
	rp.ServeHTTP(c.Writer, c.Request)
}
