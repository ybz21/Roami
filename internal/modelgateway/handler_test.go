package modelgateway

import (
	"bufio"
	"context"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	metadb "github.com/ybz21/Roami/internal/storage"
)

const billableEvents = "data: {\"choices\":[{\"delta\":{\"content\":\"hello\"},\"finish_reason\":\"stop\"}]}\n\ndata: {\"choices\":[],\"usage\":{\"prompt_tokens\":1000000,\"completion_tokens\":125000,\"prompt_tokens_details\":{\"cached_tokens\":500000}}}\n\ndata: [DONE]\n\n"

func modelRequest(target string) *http.Request {
	r := httptest.NewRequest("POST", "/v1/chat/completions", strings.NewReader(`{"model":"fixture","messages":[{"role":"user","content":"private prompt"}],"stream":true}`))
	r.Header.Set("X-Roami-Model-Upstream", target+"/custom/v1/chat/completions")
	r.Header.Set("X-Roami-Model-Role", "worker")
	r.Header.Set("X-Roami-Owner", "must-not-leak")
	r.Header.Set("Authorization", "Bearer fixture-credential")
	return r
}

func TestGatewayStreamsAccountsAndRejectsBeforeUpstream(t *testing.T) {
	l := newLedger(t)
	limit := 2.0
	if err := l.Configure(testConfiguration(&limit)); err != nil {
		t.Fatal(err)
	}
	var hits atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		if r.URL.Path != "/custom/v1/chat/completions" || r.Header.Get("Authorization") != "Bearer node-key" || r.Header.Get("X-Roami-Owner") != "" || r.Header.Get("X-Roami-Model-Upstream") != "" {
			t.Error("upstream path/auth/private metadata mismatch")
		}
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("X-Request-Id", "upstream-receipt")
		for _, line := range strings.SplitAfter(billableEvents, "\n") {
			_, _ = io.WriteString(w, line)
			w.(http.Flusher).Flush()
		}
	}))
	defer upstream.Close()
	h := nodeConfiguredHandler(t, l, upstream.URL)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, modelRequest(upstream.URL))
	if w.Code != 200 || w.Body.String() != billableEvents || !w.Flushed || w.Header().Get("X-Request-Id") != "upstream-receipt" {
		t.Fatalf("stream changed: %d %s", w.Code, w.Body.String())
	}
	w = httptest.NewRecorder()
	h.ServeHTTP(w, modelRequest(upstream.URL))
	if w.Code != 402 || hits.Load() != 1 {
		t.Fatalf("quota bypass: %d hits=%d", w.Code, hits.Load())
	}
	stats, err := l.Statistics(7)
	if err != nil || stats.Today[0].Cost != "2.000000000" {
		t.Fatalf("bill: %+v %v", stats, err)
	}
}

func TestUsageCaptureChunkBoundariesAndInvalidUsage(t *testing.T) {
	c := usageCapture{stream: true}
	for _, value := range []byte(billableEvents) {
		c.feed([]byte{value})
	}
	if u := c.finish(true); u == nil || u.Cached != 500000 {
		t.Fatalf("fragmented usage: %+v", u)
	}
	for _, body := range []string{
		`{"usage":{"prompt_tokens":true,"completion_tokens":1}}`,
		`{"usage":{"prompt_tokens":1,"completion_tokens":1,"prompt_tokens_details":{"cached_tokens":2}}}`,
		`{"usage":{"prompt_tokens":null,"completion_tokens":1}}`,
		`{"usage":{"prompt_tokens":-1,"completion_tokens":1}}`,
	} {
		if parseUsage([]byte(body)) != nil {
			t.Fatalf("invalid usage accepted: %s", body)
		}
	}
	c = usageCapture{stream: true}
	c.feed([]byte(strings.TrimSuffix(billableEvents, "data: [DONE]\n\n")))
	if c.finish(true) != nil {
		t.Fatal("incomplete stream charged as complete")
	}
	c = usageCapture{stream: true}
	c.feed([]byte(billableEvents))
	if c.finish(false) == nil {
		t.Fatal("terminal usage lost when the caller closes after DONE")
	}
	c = usageCapture{stream: true}
	c.feed([]byte("data: " + strings.Repeat("x", 2<<20) + "\n" + billableEvents))
	if c.finish(true) != nil || len(c.buffer) > 1<<20 {
		t.Fatal("unbounded or invalid event accepted")
	}
}

func TestTerminalUsageSettlesWhenCallerClosesBeforeHTTPBodyEnds(t *testing.T) {
	l := newLedger(t)
	limit := 2.0
	if err := l.Configure(testConfiguration(&limit)); err != nil {
		t.Fatal(err)
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		_, _ = io.WriteString(w, billableEvents)
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	}))
	defer upstream.Close()
	gateway := httptest.NewServer(nodeConfiguredHandler(t, l, upstream.URL))
	defer gateway.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	r := modelRequest(upstream.URL).WithContext(ctx)
	r.URL.Scheme, r.URL.Host = "http", strings.TrimPrefix(gateway.URL, "http://")
	r.RequestURI = ""
	response, err := http.DefaultClient.Do(r)
	if err != nil {
		t.Fatal(err)
	}
	reader := bufio.NewReader(response.Body)
	for {
		line, err := reader.ReadString('\n')
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(line, "[DONE]") {
			break
		}
	}
	response.Body.Close()
	cancel()
	deadline := time.Now().Add(2 * time.Second)
	for {
		stats, err := l.Statistics(1)
		if err != nil {
			t.Fatal(err)
		}
		if len(stats.Recent) == 1 && stats.Recent[0].State != "pending" {
			if stats.Recent[0].State != "known" || stats.Recent[0].Cost == nil || *stats.Recent[0].Cost != "2.000000000" {
				t.Fatalf("terminal receipt lost: %+v", stats.Recent[0])
			}
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("call did not settle after cancellation")
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestHTTPFailuresUnknownUsageAndNoRedirect(t *testing.T) {
	for _, status := range []int{0, 200, 302, 401, 500} {
		name := http.StatusText(status)
		if status == 0 {
			name = "TransportFailure"
		}
		t.Run(name, func(t *testing.T) {
			l := newLedger(t)
			if err := l.Configure(testConfiguration(nil)); err != nil {
				t.Fatal(err)
			}
			up := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Location", "http://must-not-follow.invalid")
				w.Header().Set("X-Roami-Model-Call", "forged-upstream-id")
				w.WriteHeader(status)
				_, _ = io.WriteString(w, `{"error":"fixture"}`)
			}))
			defer up.Close()
			w := httptest.NewRecorder()
			handler := nodeConfiguredHandler(t, l, up.URL)
			expected := status
			if status == 0 {
				socket := filepath.Join(t.TempDir(), "missing.sock")
				handler.Client.Transport = &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
					return (&net.Dialer{}).DialContext(ctx, "unix", socket)
				}}
				expected = 502
			}
			handler.ServeHTTP(w, modelRequest(up.URL))
			if w.Code != expected {
				t.Fatalf("status: %d", w.Code)
			}
			stats, err := l.Statistics(1)
			if err != nil {
				t.Fatal(err)
			}
			if callID := w.Header().Get("X-Roami-Model-Call"); callID == "" || callID != stats.Recent[0].ID {
				t.Fatalf("response cannot correlate to the Go ledger: %q", callID)
			}
			unknown := status == 200 || status == 500
			if (stats.Recent[0].Cost == nil) != unknown {
				t.Fatalf("failure accounting: %+v", stats.Recent[0])
			}
		})
	}
}

func TestServiceSocketLockAndRecovery(t *testing.T) {
	root := t.TempDir()
	paths, err := metadb.ResolvePaths(root, root)
	if err != nil {
		t.Fatal(err)
	}
	socket := Socket(filepath.Join(root, "agent.sock"))
	stop, err := Start(paths, socket)
	if err != nil {
		t.Fatal(err)
	}
	defer stop()
	info, err := os.Stat(socket)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("socket privacy: %v", err)
	}
	if duplicate, err := Start(paths, socket); err == nil {
		duplicate()
		t.Fatal("duplicate owner started")
	}
	l, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	defer metadb.Discard(l.db.Path())
	if err = l.Configure(testConfiguration(nil)); err != nil {
		t.Fatal(err)
	}
	if _, err = l.Admit("main", "fixture", "", ""); err != nil {
		t.Fatal(err)
	}
	stop()
	restarted, err := Start(paths, socket)
	if err != nil {
		t.Fatal(err)
	}
	defer restarted()
	stats, err := l.Statistics(1)
	if err != nil || stats.Recent[0].State != "unknown" {
		t.Fatalf("recovery: %+v %v", stats, err)
	}
}
