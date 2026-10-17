package main

import (
	"bytes"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// peekedConn 把偷看掉的那个字节还回去。这段最容易写错——少还一个字节，
// TLS 握手就解析失败，表现是「HTTPS 偶尔连不上」，而不是一眼可见的报错。
func TestPeekedConnReplaysFirstByte(t *testing.T) {
	cases := []struct {
		name    string
		payload string
		bufSize int
	}{
		{"一次读完", "GET / HTTP/1.1\r\n\r\n", 64},
		{"缓冲区只有 1 字节", "GET /", 1},
		{"缓冲区正好 2 字节", "GET /", 2},
		{"只有一个字节可读", "G", 64},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			cli, srv := net.Pipe()
			go func() { _, _ = cli.Write([]byte(c.payload)); _ = cli.Close() }()

			var first [1]byte
			if _, err := io.ReadFull(srv, first[:]); err != nil {
				t.Fatal(err)
			}
			pc := &peekedConn{Conn: srv, first: []byte{first[0]}, unread: true}

			var got bytes.Buffer
			buf := make([]byte, c.bufSize)
			for {
				n, err := pc.Read(buf)
				got.Write(buf[:n])
				if err != nil {
					break
				}
				if got.Len() >= len(c.payload) {
					break
				}
			}
			if got.String() != c.payload {
				t.Errorf("还原出来的是 %q，原文是 %q", got.String(), c.payload)
			}
		})
	}
}

// 明文请求要跳到 https，且**保留路径与查询串** —— 少了它，
// 手机上从书签点进来会被扔回首页，还得重新找一遍。
func TestRedirectKeepsPathAndQuery(t *testing.T) {
	r := httptest.NewRequest(http.MethodGet, "http://box:13579/api/sessions?tree=1", nil)
	w := httptest.NewRecorder()
	redirectToHTTPS(w, r)
	if w.Code != http.StatusMovedPermanently {
		t.Errorf("GET 该用 301，得到 %d", w.Code)
	}
	if got := w.Header().Get("Location"); got != "https://box:13579/api/sessions?tree=1" {
		t.Errorf("Location = %q", got)
	}
}

// 非 GET 必须用 308：301 会让浏览器把 POST 改写成 GET、请求体丢掉，
// 那种「表单提交一次就没了」的故障最难查。
func TestRedirectPreservesMethodForPost(t *testing.T) {
	r := httptest.NewRequest(http.MethodPost, "http://box:13579/api/login", nil)
	w := httptest.NewRecorder()
	redirectToHTTPS(w, r)
	if w.Code != http.StatusPermanentRedirect {
		t.Errorf("POST 该用 308，得到 %d", w.Code)
	}
}

// chanListener 关闭后 Accept 要立刻返回，别把 server 的 goroutine 挂住。
func TestChanListenerCloseUnblocksAccept(t *testing.T) {
	l := newChanListener(&net.TCPAddr{})
	done := make(chan struct{})
	go func() { _, _ = l.Accept(); close(done) }()
	l.Close()
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Close 之后 Accept 没返回")
	}
	// 关掉之后再喂连接不该 panic（Accept 循环可能还在跑最后一轮）
	c1, c2 := net.Pipe()
	defer c2.Close()
	l.put(c1)
}
