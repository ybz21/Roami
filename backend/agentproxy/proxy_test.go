package agentproxy

import (
	"bufio"
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"path/filepath"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
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
	finished := make(chan struct{})
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
			return
		}
		_, _ = io.WriteString(w, "id: 2\nevent: message.delta\ndata: {\"text\":\"second\"}\n\n")
		w.(http.Flusher).Flush()
		select {
		case <-finished:
		case <-r.Context().Done():
		}
	})}
	go func() { _ = server.Serve(listener) }()
	defer server.Close()
	gin.SetMode(gin.TestMode)
	router := gin.New()
	handler := Proxy(socket)
	router.GET("/api/agent/conversations/:cid/events", func(c *gin.Context) {
		handler.ServeHTTP(c.Writer, c.Request)
	})
	proxy := httptest.NewServer(router)
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
	reader := bufio.NewReader(res.Body)
	for _, expected := range []string{"id: 1\n", "event: message.delta\n", "data: {}\n", "\n"} {
		line, err := reader.ReadString('\n')
		if err != nil || line != expected {
			t.Fatalf("first event before release: got %q, want %q: %v", line, expected, err)
		}
	}
	close(released)
	for _, expected := range []string{"id: 2\n", "event: message.delta\n", "data: {\"text\":\"second\"}\n", "\n"} {
		line, err := reader.ReadString('\n')
		if err != nil || line != expected {
			t.Fatalf("second event before finish: got %q, want %q: %v", line, expected, err)
		}
	}
	close(finished)
}
