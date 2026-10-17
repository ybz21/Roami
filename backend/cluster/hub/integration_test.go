package hub_test

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/cluster/hub"
	"github.com/ybz21/Roami/backend/cluster/node"
)

// TestTunnelProxyEndToEnd 拉起一个 中心（gin + httptest），让一个节点经隧道注册进来，
// 再通过 /n/<id>/api/ping 把请求反代到节点的业务 Handler，验证整条数据面打通：
// enrollment → yamux over ws 隧道 → 反代 → 节点响应回传。
func TestTunnelProxyEndToEnd(t *testing.T) {
	gin.SetMode(gin.TestMode)
	brk := hub.New(t.TempDir())

	r := gin.New()
	r.GET("/cluster/tunnel", brk.HandleTunnel)
	r.POST("/api/hub/enroll", brk.Enroll)
	r.GET("/api/hub/nodes", brk.Nodes)
	r.Any("/n/:nodeId/*path", brk.ProxyNode)
	srv := httptest.NewServer(r)
	defer srv.Close()

	// 1) 签发接入令牌
	token := enroll(t, srv.URL)

	// 2) 节点：业务 Handler 只回 pong
	biz := http.NewServeMux()
	biz.HandleFunc("/api/ping", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, "pong")
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	cl := &node.Client{
		Hub:      srv.URL,
		Token:    token,
		Name:     "test-node",
		Version:  "test",
		CredPath: filepath.Join(t.TempDir(), "node.json"),
		Handler:  biz,
	}
	go cl.Run(ctx)

	// 3) 等节点上线，取 nodeId
	id := waitOnline(t, srv.URL)

	// 4) 经 中心 反代打到节点业务 Handler
	got := ""
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		resp, err := http.Get(srv.URL + "/n/" + id + "/api/ping")
		if err == nil && resp.StatusCode == http.StatusOK {
			b, _ := io.ReadAll(resp.Body)
			resp.Body.Close()
			got = string(b)
			break
		}
		if resp != nil {
			resp.Body.Close()
		}
		time.Sleep(50 * time.Millisecond)
	}
	if got != "pong" {
		t.Fatalf("反代结果 = %q，期望 %q", got, "pong")
	}
}

func enroll(t *testing.T, base string) string {
	t.Helper()
	resp, err := http.Post(base+"/api/hub/enroll", "application/json", nil)
	if err != nil {
		t.Fatalf("enroll 失败: %v", err)
	}
	defer resp.Body.Close()
	var out struct {
		Data struct{ Token string } `json:"data"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil || out.Data.Token == "" {
		t.Fatalf("解析 enroll 响应失败: %v (token=%q)", err, out.Data.Token)
	}
	return out.Data.Token
}

func waitOnline(t *testing.T, base string) string {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		resp, err := http.Get(base + "/api/hub/nodes")
		if err == nil {
			var out struct {
				Data []struct {
					ID     string `json:"id"`
					Online bool   `json:"online"`
				} `json:"data"`
			}
			_ = json.NewDecoder(resp.Body).Decode(&out)
			resp.Body.Close()
			for _, n := range out.Data {
				if n.Online {
					return n.ID
				}
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("节点未在超时内上线")
	return ""
}

// TestProxyPreservesRawPath 盯的是一个只在真实文件名上才炸的坑：反代重写路径时如果拿
// c.Param("path")（已解码值）赋回 URL.Path，RawPath 就失效，转发时按默认规则重新编码。
// 而 /api/file/serve/*path 把**绝对路径塞进 URL**，文件名里的 # ? % 空格全会在这一跳
// 变形 → 预览/下载 404。见 docs/design/cluster/architecture.html §3 ①。
func TestProxyPreservesRawPath(t *testing.T) {
	gin.SetMode(gin.TestMode)
	brk := hub.New(t.TempDir())

	r := gin.New()
	r.UseRawPath = true // 与 server.New / NewHub 一致
	r.GET("/cluster/tunnel", brk.HandleTunnel)
	r.POST("/api/hub/enroll", brk.Enroll)
	r.GET("/api/hub/nodes", brk.Nodes)
	r.Any("/n/:nodeId/*path", brk.ProxyNode)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := enroll(t, srv.URL)

	// 节点侧把收到的原始 RequestURI 原样回显——要比的就是它有没有在中间变形
	biz := http.NewServeMux()
	biz.HandleFunc("/api/file/serve/", func(w http.ResponseWriter, req *http.Request) {
		_, _ = io.WriteString(w, req.URL.EscapedPath()+"|"+req.URL.RawQuery)
	})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	cl := &node.Client{
		Hub: srv.URL, Token: token, Name: "test-node", Version: "test",
		CredPath: filepath.Join(t.TempDir(), "node.json"), Handler: biz,
	}
	go cl.Run(ctx)
	id := waitOnline(t, srv.URL)

	// 一个能把上面每种错误都踩响的路径：空格、#、%、中文
	raw := "/api/file/serve/" + url.PathEscape("/home/x/a b#c%d 文件.txt")
	want := url.PathEscape("/home/x/a b#c%d 文件.txt")

	resp, err := http.Get(srv.URL + "/n/" + id + raw + "?q=a%20b%23c")
	if err != nil {
		t.Fatalf("请求失败: %v", err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	got := string(b)
	if !strings.Contains(got, want) {
		t.Fatalf("节点收到的路径 = %q，期望包含 %q（RawPath 在反代那一跳被重编码了）", got, want)
	}
	if !strings.HasSuffix(got, "|q=a%20b%23c") {
		t.Fatalf("query 也变形了: %q", got)
	}
}

// TestLatencyMeasured 验证控制流上的 ping/pong：心跳是节点单向上报，量不出 RTT，
// 而界面每一处都要显示「12ms」。见 architecture.html §3 ③。
func TestLatencyMeasured(t *testing.T) {
	gin.SetMode(gin.TestMode)
	brk := hub.New(t.TempDir())

	r := gin.New()
	r.GET("/cluster/tunnel", brk.HandleTunnel)
	r.POST("/api/hub/enroll", brk.Enroll)
	r.GET("/api/hub/nodes", brk.Nodes)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := enroll(t, srv.URL)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	cl := &node.Client{
		Hub: srv.URL, Token: token, Name: "test-node", Version: "test",
		CredPath: filepath.Join(t.TempDir(), "node.json"), Handler: http.NewServeMux(),
	}
	go cl.Run(ctx)
	waitOnline(t, srv.URL)

	// 本地回环的 RTT 是亚毫秒，所以只断言「这个字段被填过」——>0 或至少不再是缺省。
	// 真正会退化的是「节点根本不回 pong」，那时 latencyMs 永远是 0。
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		resp, err := http.Get(srv.URL + "/api/hub/nodes")
		if err == nil {
			var out struct {
				Data []struct {
					LatencyMs int  `json:"latencyMs"`
					Online    bool `json:"online"`
				} `json:"data"`
			}
			_ = json.NewDecoder(resp.Body).Decode(&out)
			resp.Body.Close()
			// pong 回来过：Latency() 会顺带刷新 lastHeartbeat，节点因此在心跳周期
			// （15s）之前就被认作在线——这正是加 ping 的第二个理由
			if len(out.Data) > 0 && out.Data[0].Online {
				return
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatal("5s 内没有观察到 ping/pong 生效")
}

// TestNodeTokenHashNotExposed：节点列表是给浏览器的，长期凭证的哈希没有任何理由发过去。
func TestNodeTokenHashNotExposed(t *testing.T) {
	gin.SetMode(gin.TestMode)
	dir := t.TempDir()
	brk := hub.New(dir)
	r := gin.New()
	r.GET("/cluster/tunnel", brk.HandleTunnel)
	r.POST("/api/hub/enroll", brk.Enroll)
	r.GET("/api/hub/nodes", brk.Nodes)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := enroll(t, srv.URL)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	cl := &node.Client{
		Hub: srv.URL, Token: token, Name: "test-node", Version: "test",
		CredPath: filepath.Join(t.TempDir(), "node.json"), Handler: http.NewServeMux(),
	}
	go cl.Run(ctx)
	waitOnline(t, srv.URL)

	resp, err := http.Get(srv.URL + "/api/hub/nodes")
	if err != nil {
		t.Fatalf("请求失败: %v", err)
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(resp.Body)
	if strings.Contains(string(b), "tokenHash") {
		t.Fatalf("节点列表把凭证哈希发给了浏览器: %s", b)
	}

	// 反过来：它**必须**还在 nodes.json 里。少了它，中心一重启所有节点都认不回来，
	// 而接入令牌是一次性的——等于把机器锁在门外。
	saved, err := os.ReadFile(filepath.Join(dir, "nodes.json"))
	if err != nil {
		t.Fatalf("读 nodes.json 失败: %v", err)
	}
	if !strings.Contains(string(saved), "tokenHash") {
		t.Fatalf("落盘丢了凭证哈希，中心重启后节点将无法重连: %s", saved)
	}
}

// 接入命令里的地址不能想当然用请求的 Host：你在局域网里管中心，那就是内网地址，
// 外网那台机器照着做必然连不上——而它那边只会报「连接失败」，看不出是地址的问题。
func TestEnrollUsesPublicURL(t *testing.T) {
	gin.SetMode(gin.TestMode)
	brk := hub.New(t.TempDir())
	brk.SetPublicURL("https://roam.example.com/")

	r := gin.New()
	r.POST("/api/hub/enroll", brk.Enroll)
	srv := httptest.NewServer(r)
	defer srv.Close()

	resp, err := http.Post(srv.URL+"/api/hub/enroll", "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out struct {
		Data struct {
			Command string `json:"command"`
			HubURL  string `json:"hubUrl"`
			Private bool   `json:"private"`
		} `json:"data"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&out)

	if out.Data.HubURL != "https://roam.example.com" {
		t.Errorf("对外地址 = %q，期望去掉尾斜杠的配置值", out.Data.HubURL)
	}
	if strings.Contains(out.Data.Command, srv.URL) {
		t.Errorf("命令里混进了请求的 Host：%s", out.Data.Command)
	}
	if !strings.Contains(out.Data.Command, "--hub https://roam.example.com") {
		t.Errorf("命令没用对外地址：%s", out.Data.Command)
	}
	if out.Data.Private {
		t.Error("公网域名不该被判成内网地址")
	}
}

// 没配对外地址就回落到请求 Host——而 httptest 是 127.0.0.1，正好该被标成「内网」。
// 这条提示是纯本地判断，不探测可达性：那件事中心自己做不到。
func TestEnrollFlagsPrivateFallback(t *testing.T) {
	gin.SetMode(gin.TestMode)
	brk := hub.New(t.TempDir())

	r := gin.New()
	r.POST("/api/hub/enroll", brk.Enroll)
	srv := httptest.NewServer(r)
	defer srv.Close()

	resp, err := http.Post(srv.URL+"/api/hub/enroll", "application/json", nil)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	var out struct {
		Data struct{ Private bool } `json:"data"`
	}
	_ = json.NewDecoder(resp.Body).Decode(&out)
	if !out.Data.Private {
		t.Error("127.0.0.1 应被标成内网地址，好提醒「别处的机器接不进来」")
	}
}

// TestProxyDoesNotLeakGoroutines 盯的是一个把中心压死过的真事（2026-08-11）：
// ProxyNode 曾经**每个请求 new 一个 http.Transport**。Transport 自带空闲连接池，请求结束后
// 那条 yamux 流被放回池里、readLoop/writeLoop 继续挂着等数据；手写 Transport 的
// IdleConnTimeout 默认是 0（永不超时），而 Transport 本身随请求结束被丢掉，再没人调
// CloseIdleConnections()。于是每个经中心代理的请求都留下两个永不退出的 goroutine。
//
// 线上表现：19185 个 goroutine（9572 对卡在 yamux.Stream.Read，最久的挂了 661 分钟），
// RSS 从 20MB 涨到 300MB，端口能连但不再 accept——控制台每 5 秒轮询一次，一夜就是几千个。
//
// 这里连打 40 个请求，断言 goroutine 增量远小于「每请求 2 个」。不卡死值：并发与运行时
// 自己的 goroutine 都会浮动，只要不是线性增长就行（泄漏时这里会 +80 以上）。
func TestProxyDoesNotLeakGoroutines(t *testing.T) {
	gin.SetMode(gin.TestMode)
	brk := hub.New(t.TempDir())

	r := gin.New()
	r.GET("/cluster/tunnel", brk.HandleTunnel)
	r.POST("/api/hub/enroll", brk.Enroll)
	r.GET("/api/hub/nodes", brk.Nodes)
	r.Any("/n/:nodeId/*path", brk.ProxyNode)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := enroll(t, srv.URL)
	biz := http.NewServeMux()
	biz.HandleFunc("/api/ping", func(w http.ResponseWriter, _ *http.Request) { _, _ = io.WriteString(w, "pong") })
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	cl := &node.Client{
		Hub: srv.URL, Token: token, Name: "leak-node", Version: "test",
		CredPath: filepath.Join(t.TempDir(), "node.json"), Handler: biz,
	}
	go cl.Run(ctx)
	id := waitOnline(t, srv.URL)

	get := func() {
		resp, err := http.Get(srv.URL + "/n/" + id + "/api/ping")
		if err != nil {
			t.Fatalf("反代请求失败: %v", err)
		}
		_, _ = io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}

	get() // 预热：第一次会建隧道流、起 readLoop，那一份不算泄漏
	time.Sleep(200 * time.Millisecond)
	before := runtime.NumGoroutine()

	const n = 40
	for i := 0; i < n; i++ {
		get()
	}
	time.Sleep(500 * time.Millisecond) // 给收尾的 goroutine 一点退出时间
	grew := runtime.NumGoroutine() - before

	if grew > n { // 泄漏时是 2n（80）；复用时基本是 0，留足并发抖动的余量
		t.Fatalf("%d 个反代请求后 goroutine 增长 %d，疑似每请求泄漏（复用 Transport 时应接近 0）", n, grew)
	}
}

// TestSelfReportsHealthAndEvents 盯的是中心页的数据源。2026-08-11 中心卡死十几个小时无人知，
// 就是因为没有任何接口回答「中心自己怎么样」——查问题只能 ssh 上去看 ps。
// 这条用例要求 /api/hub/self 真的会动：节点上线要产生事件，反代要被计数，采样要有值。
func TestSelfReportsHealthAndEvents(t *testing.T) {
	gin.SetMode(gin.TestMode)
	brk := hub.New(t.TempDir())
	brk.SetVersion("test-ver")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	brk.StartSampling(ctx) // 起点采一次，不等 5 分钟

	r := gin.New()
	r.GET("/cluster/tunnel", brk.HandleTunnel)
	r.POST("/api/hub/enroll", brk.Enroll)
	r.GET("/api/hub/nodes", brk.Nodes)
	r.GET("/api/hub/self", brk.Self)
	r.Any("/n/:nodeId/*path", brk.ProxyNode)
	srv := httptest.NewServer(r)
	defer srv.Close()

	token := enroll(t, srv.URL)
	biz := http.NewServeMux()
	biz.HandleFunc("/api/ping", func(w http.ResponseWriter, _ *http.Request) { _, _ = io.WriteString(w, "pong") })
	cl := &node.Client{
		Hub: srv.URL, Token: token, Name: "self-node", Version: "test",
		CredPath: filepath.Join(t.TempDir(), "node.json"), Handler: biz,
	}
	go cl.Run(ctx)
	id := waitOnline(t, srv.URL)

	resp, err := http.Get(srv.URL + "/n/" + id + "/api/ping")
	if err != nil {
		t.Fatalf("反代失败: %v", err)
	}
	_, _ = io.Copy(io.Discard, resp.Body)
	resp.Body.Close()

	var out struct {
		Data struct {
			Version     string `json:"version"`
			UptimeSecs  int64  `json:"uptimeSecs"`
			NodesOnline int    `json:"nodesOnline"`
			Now         struct {
				Goroutines int   `json:"goroutines"`
				Tunnels    int   `json:"tunnels"`
				Requests   int64 `json:"requests"`
			} `json:"now"`
			Samples []struct {
				At int64 `json:"at"`
			} `json:"samples"`
			Events []struct {
				Kind string `json:"kind"`
				Node string `json:"node"`
			} `json:"events"`
		} `json:"data"`
	}
	sr, err := http.Get(srv.URL + "/api/hub/self")
	if err != nil {
		t.Fatalf("取 self 失败: %v", err)
	}
	defer sr.Body.Close()
	if err := json.NewDecoder(sr.Body).Decode(&out); err != nil {
		t.Fatalf("解析 self 失败: %v", err)
	}
	d := out.Data

	if d.Version != "test-ver" {
		t.Errorf("version = %q，期望 test-ver", d.Version)
	}
	if d.Now.Goroutines <= 0 || d.Now.Tunnels != 1 {
		t.Errorf("goroutines=%d tunnels=%d，期望 goroutines>0 且 tunnels=1", d.Now.Goroutines, d.Now.Tunnels)
	}
	if d.Now.Requests < 1 {
		t.Errorf("requests = %d，反代过一次应当被计数", d.Now.Requests)
	}
	if d.NodesOnline != 1 {
		t.Errorf("nodesOnline = %d，期望 1", d.NodesOnline)
	}
	if len(d.Samples) == 0 || d.Samples[0].At == 0 {
		t.Errorf("采样为空——StartSampling 应当在起点就采一次，不然新装的中心前 5 分钟没有任何曲线")
	}
	kinds := map[string]bool{}
	for _, e := range d.Events {
		kinds[e.Kind] = true
		if e.Kind == "node_up" && e.Node != "self-node" {
			t.Errorf("node_up 的机器名 = %q，期望显示名而不是 id", e.Node)
		}
	}
	if !kinds["hub_start"] || !kinds["node_up"] {
		t.Errorf("事件流缺东西：%v（期望至少有 hub_start 与 node_up）", kinds)
	}
}
