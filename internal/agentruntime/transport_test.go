package agentruntime

import (
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	metadb "github.com/ybz21/Roami/internal/storage"
)

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

func TestPathsBoundToCatalogInstance(t *testing.T) {
	home := t.TempDir()
	p, err := metadb.ResolvePaths(home, home)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = p.Ensure(); err != nil {
		t.Fatal(err)
	}
	runtime := t.TempDir()
	if err = os.Chmod(runtime, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("XDG_RUNTIME_DIR", runtime)
	first, err := Resolve(home, home)
	if err != nil {
		t.Fatal(err)
	}
	other := t.TempDir()
	p2, err := metadb.ResolvePaths(other, other)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = p2.Ensure(); err != nil {
		t.Fatal(err)
	}
	second, err := Resolve(other, other)
	if err != nil {
		t.Fatal(err)
	}
	if first.Socket == second.Socket || first.InstanceID == second.InstanceID {
		t.Fatal("instances share runtime identity")
	}
	if first.Database != filepath.Join(p.Database, "agents", "runtime.db") {
		t.Fatal(first.Database)
	}
}
