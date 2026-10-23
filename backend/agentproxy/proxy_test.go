package agentproxy

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"path/filepath"
	"testing"
	"time"
)

func TestCapabilityDownloadUsesBoundedLongerHeaderBudget(t *testing.T) {
	proxy := Proxy("/tmp/unused-roami-test.sock").(*httputil.ReverseProxy)
	transport := proxy.Transport.(capabilityTransport)
	if transport.standard.ResponseHeaderTimeout != 15*time.Second || transport.marketplace.ResponseHeaderTimeout != 100*time.Second {
		t.Fatal("ordinary requests and capability downloads must keep distinct bounded budgets")
	}
}

func TestProxyIdentityStreamingAndPath(t *testing.T) {
	socket := filepath.Join(t.TempDir(), "agent.sock")
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	released := make(chan struct{})
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/conversations/c1/events" || r.Header.Get("X-Roami-Owner") != "local" || r.Header.Get("Cookie") != "" || r.Header.Get("Authorization") != "" {
			t.Errorf("invalid forwarded request: %s owner=%s", r.URL.Path, r.Header.Get("X-Roami-Owner"))
		}
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, "id: 1\nevent: message.delta\ndata: {}\n\n")
		w.(http.Flusher).Flush()
		select {
		case <-released:
		case <-r.Context().Done():
		}
	})}
	go func() { _ = server.Serve(listener) }()
	defer server.Close()
	proxy := httptest.NewServer(Proxy(socket))
	defer proxy.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", proxy.URL+"/api/agent/conversations/c1/events", nil)
	req.Header.Set("X-Roami-Owner", "spoofed")
	req.Header.Set("Cookie", "private-cookie")
	req.Header.Set("Authorization", "private-auth")
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	chunk := make([]byte, 5)
	if _, err = io.ReadFull(res.Body, chunk); err != nil {
		t.Fatal(err)
	}
	if string(chunk) != "id: 1" {
		t.Fatalf("stream was changed: %q", chunk)
	}
	close(released)
}
