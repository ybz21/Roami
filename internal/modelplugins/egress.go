package modelplugins

import (
	"context"
	"errors"
	"io"
	"net"
	"net/http"
	"net/netip"
	"os"
	"strings"
	"sync"
	"time"
)

// Egress exposes public HTTP(S) only. The worker never shares host loopback,
// where Roami's management sockets and the user's browser debugging port live.
type Egress struct {
	server   *http.Server
	listener net.Listener
	mu       sync.Mutex
	tunnels  map[net.Conn]struct{}
	slots    chan struct{}
	closed   bool
}

func NewEgress(socket string) (*Egress, error) {
	listener, err := net.Listen("unix", socket)
	if err != nil {
		return nil, err
	}
	if err = os.Chmod(socket, 0600); err != nil {
		_ = listener.Close()
		return nil, err
	}
	e := &Egress{listener: listener, tunnels: map[net.Conn]struct{}{}, slots: make(chan struct{}, 32)}
	e.server = &http.Server{Handler: e, ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 32 << 10}
	go func() { _ = e.server.Serve(listener) }()
	return e, nil
}
func (e *Egress) Close() error {
	e.mu.Lock()
	e.closed = true
	for c := range e.tunnels {
		_ = c.Close()
	}
	e.mu.Unlock()
	return e.server.Close()
}
func publicAddress(ip netip.Addr) bool {
	ip = ip.Unmap()
	if !ip.IsValid() || !ip.IsGlobalUnicast() || ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast() {
		return false
	}
	for _, cidr := range []string{"0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "240.0.0.0/4", "2001:db8::/32", "2001::/32", "::/96", "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16"} {
		if netip.MustParsePrefix(cidr).Contains(ip) {
			return false
		}
	}
	return true
}
func publicDial(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil || port != "80" && port != "443" {
		return nil, errors.New("MODEL_PLUGIN_EGRESS_DENIED")
	}
	ips, err := net.DefaultResolver.LookupNetIP(ctx, "ip", host)
	if err != nil || len(ips) == 0 {
		return nil, errors.New("MODEL_PLUGIN_EGRESS_UNAVAILABLE")
	}
	// Reject mixed public/private DNS answers instead of picking the public one.
	for _, ip := range ips {
		if !publicAddress(ip) {
			return nil, errors.New("MODEL_PLUGIN_EGRESS_DENIED")
		}
	}
	dialer := net.Dialer{Timeout: 15 * time.Second, KeepAlive: 30 * time.Second}
	var last error
	for _, ip := range ips {
		conn, err := dialer.DialContext(ctx, network, net.JoinHostPort(ip.String(), port))
		if err == nil {
			return conn, nil
		}
		last = err
	}
	return nil, last
}
func (e *Egress) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	select {
	case e.slots <- struct{}{}:
		defer func() { <-e.slots }()
	default:
		http.Error(w, "MODEL_PLUGIN_EGRESS_BUSY", 503)
		return
	}
	if r.Method == "CONNECT" {
		e.connect(w, r)
		return
	}
	if r.URL.Scheme != "http" || r.URL.Host == "" || r.URL.User != nil {
		http.Error(w, "MODEL_PLUGIN_EGRESS_DENIED", 403)
		return
	}
	req := r.Clone(r.Context())
	req.RequestURI = ""
	req.Header.Del("Proxy-Authorization")
	req.Header.Del("Proxy-Connection")
	transport := &http.Transport{DialContext: publicDial, DisableKeepAlives: true, ResponseHeaderTimeout: 60 * time.Second}
	defer transport.CloseIdleConnections()
	res, err := transport.RoundTrip(req)
	if err != nil {
		http.Error(w, "MODEL_PLUGIN_EGRESS_UNAVAILABLE", 502)
		return
	}
	defer res.Body.Close()
	for k, values := range res.Header {
		if strings.EqualFold(k, "Connection") || strings.EqualFold(k, "Transfer-Encoding") {
			continue
		}
		for _, v := range values {
			w.Header().Add(k, v)
		}
	}
	w.WriteHeader(res.StatusCode)
	_, _ = io.Copy(w, res.Body)
}
func (e *Egress) connect(w http.ResponseWriter, r *http.Request) {
	upstream, err := publicDial(r.Context(), "tcp", r.Host)
	if err != nil {
		http.Error(w, "MODEL_PLUGIN_EGRESS_DENIED", 403)
		return
	}
	defer upstream.Close()
	hijacker, ok := w.(http.Hijacker)
	if !ok {
		http.Error(w, "MODEL_PLUGIN_EGRESS_UNAVAILABLE", 502)
		return
	}
	client, buffer, err := hijacker.Hijack()
	if err != nil {
		return
	}
	defer client.Close()
	e.mu.Lock()
	if e.closed {
		e.mu.Unlock()
		return
	}
	e.tunnels[client] = struct{}{}
	e.tunnels[upstream] = struct{}{}
	e.mu.Unlock()
	defer func() { e.mu.Lock(); delete(e.tunnels, client); delete(e.tunnels, upstream); e.mu.Unlock() }()
	_ = client.SetDeadline(time.Now().Add(20 * time.Minute))
	_ = upstream.SetDeadline(time.Now().Add(20 * time.Minute))
	if _, err = buffer.WriteString("HTTP/1.1 200 Connection Established\r\n\r\n"); err != nil {
		return
	}
	if buffer.Flush() != nil {
		return
	}
	done := make(chan struct{})
	go func() { _, _ = io.Copy(upstream, buffer); _ = upstream.Close(); close(done) }()
	_, _ = io.Copy(client, upstream)
	_ = client.Close()
	<-done
}
