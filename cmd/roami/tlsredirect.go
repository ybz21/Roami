package main

import (
	"crypto/tls"
	"log"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"
)

// 同一个端口上既收 HTTPS，也把误打进来的明文 HTTP 请求 301 到 HTTPS。
//
// 从前用 gin 的 RunTLS（= http.ListenAndServeTLS），它只认 TLS 握手：
// 浏览器地址栏里少打个 s，拿到的是一句
// "Client sent an HTTP request to an HTTPS server."（HTTP 400）——
// 而且是纯文本，用户看不出该怎么办，只当服务坏了。手机上尤其常见：
// 输地址靠手打，自动补全又常给出 http://。
//
// 做法是在 Accept 之后**偷看第一个字节**：TLS 记录层的握手一定以 0x16 开头，
// 而任何 HTTP 方法都以大写字母开头（GET/POST/HEAD…），两者不会混。
// 看完再把这个字节塞回去，交给对应的 server —— 谁都不知道它被看过。

// peekedConn 是把「已经读掉的第一个字节」还回去的连接。
type peekedConn struct {
	net.Conn
	first  []byte
	unread bool
}

func (c *peekedConn) Read(b []byte) (int, error) {
	if c.unread && len(b) > 0 {
		b[0] = c.first[0]
		c.unread = false
		if len(b) == 1 {
			return 1, nil
		}
		// 剩下的照常从底层读；读不到也没关系，已经有 1 字节可交付。
		n, err := c.Conn.Read(b[1:])
		if err != nil && n == 0 {
			return 1, nil
		}
		return n + 1, err
	}
	return c.Conn.Read(b)
}

// chanListener 是个「别人喂给我连接」的 listener，用来把分流后的两股连接
// 分别交给两个 http.Server。
type chanListener struct {
	ch   chan net.Conn
	addr net.Addr
	once sync.Once
	done chan struct{}
}

func newChanListener(addr net.Addr) *chanListener {
	return &chanListener{ch: make(chan net.Conn, 16), addr: addr, done: make(chan struct{})}
}

func (l *chanListener) Accept() (net.Conn, error) {
	select {
	case c := <-l.ch:
		return c, nil
	case <-l.done:
		return nil, net.ErrClosed
	}
}

func (l *chanListener) Close() error {
	l.once.Do(func() { close(l.done) })
	return nil
}

func (l *chanListener) Addr() net.Addr { return l.addr }

func (l *chanListener) put(c net.Conn) {
	select {
	case l.ch <- c:
	case <-l.done:
		_ = c.Close()
	}
}

// serveTLSWithRedirect 在 bind 上同时提供 HTTPS 服务与「明文 → HTTPS」跳转。
func serveTLSWithRedirect(h http.Handler, bind, certPath, keyPath string) error {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return err
	}
	ln, err := net.Listen("tcp", bind)
	if err != nil {
		return err
	}
	defer ln.Close()

	tlsLn := newChanListener(ln.Addr())
	plainLn := newChanListener(ln.Addr())
	defer tlsLn.Close()
	defer plainLn.Close()

	// 明文那一股只做一件事：告诉浏览器换 https 再来。不碰业务 handler，
	// 免得有人以为「其实 http 也能用」而把它当成一条正经入口。
	go func() {
		_ = (&http.Server{
			Handler:           http.HandlerFunc(redirectToHTTPS),
			ReadHeaderTimeout: 5 * time.Second,
		}).Serve(plainLn)
	}()

	srv := &http.Server{
		Handler:   h,
		TLSConfig: &tls.Config{Certificates: []tls.Certificate{cert}},
	}
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				tlsLn.Close()
				plainLn.Close()
				return
			}
			go classify(c, tlsLn, plainLn)
		}
	}()
	return srv.ServeTLS(tlsLn, "", "")
}

// classify 偷看第一个字节，决定这条连接归谁。
func classify(c net.Conn, tlsLn, plainLn *chanListener) {
	// 只为看一个字节，别让半开连接把 goroutine 永久挂住。
	_ = c.SetReadDeadline(time.Now().Add(10 * time.Second))
	var b [1]byte
	n, err := c.Read(b[:])
	if err != nil || n == 0 {
		_ = c.Close()
		return
	}
	_ = c.SetReadDeadline(time.Time{}) // 交出去之前把期限清掉，否则业务连接会被它掐断

	pc := &peekedConn{Conn: c, first: []byte{b[0]}, unread: true}
	// 0x16 = TLS 记录层的 handshake。HTTP 请求行以方法名开头，全是大写字母。
	if b[0] == 0x16 {
		tlsLn.put(pc)
		return
	}
	plainLn.put(pc)
}

func redirectToHTTPS(w http.ResponseWriter, r *http.Request) {
	host := r.Host
	if host == "" {
		host = r.URL.Host
	}
	u := url.URL{Scheme: "https", Host: host, Path: r.URL.Path, RawQuery: r.URL.RawQuery}
	// 301 而不是 302：这个跳转是永久事实（这个口就是 HTTPS），
	// 让浏览器记住，下次直接走 https，省一次明文往返。
	//
	// 但只对 GET/HEAD 用 301——其余方法用 308 保持方法与请求体不变。
	// 用 301 的话浏览器会把 POST 改写成 GET，请求体丢掉，
	// 那种「表单提交一次就没了」的故障最难查。
	code := http.StatusMovedPermanently
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		code = http.StatusPermanentRedirect
	}
	noteRedirect(host)
	w.Header().Set("Cache-Control", "no-store")
	http.Redirect(w, r, u.String(), code)
}

// logRedirectOnce 只在第一次真的跳转时说一句，免得刷日志。
var logRedirectOnce sync.Once

func noteRedirect(host string) {
	logRedirectOnce.Do(func() {
		log.Printf("有明文 HTTP 请求打到 https 口，已 301 跳转（%s）", strings.TrimSpace(host))
	})
}
