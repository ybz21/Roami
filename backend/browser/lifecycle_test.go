package browser

import (
	"context"
	"encoding/json"
	"github.com/ybz21/Roami/internal/browsertabs"
	"net/http"
	"net/http/httptest"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestChromePIDOnlyMatchesRootAtExactPort(t *testing.T) {
	ps := `11 /opt/google/chrome/chrome --type=renderer --remote-debugging-port=9222
12 /usr/bin/python3 --remote-debugging-port=9222
13 /opt/google/chrome/chrome --remote-debugging-port=92220
14 /opt/google/chrome/chrome --remote-debugging-port=9222 --user-data-dir=/tmp/profile with spaces
15 /opt/google/chrome/chrome --remote-debugging-port=9223`
	if got := chromePID(ps, 9222); got != 14 {
		t.Fatalf("got pid %d", got)
	}
	if got := chromePID(ps, 9999); got != 0 {
		t.Fatalf("got unrelated pid %d", got)
	}
}

func TestRestartRejectsRemoteAndConcurrentRequests(t *testing.T) {
	previous := cdpAddress()
	t.Cleanup(func() { setCDPAddress(previous); restarting.Store(false) })
	setCDPAddress("http://192.0.2.1:9222")
	if _, err := restartChrome(nil); err == nil || !strings.Contains(err.Error(), "remote") {
		t.Fatalf("got %v", err)
	}
	restarting.Store(true)
	if _, err := restartChrome(nil); err == nil || !strings.Contains(err.Error(), "progress") {
		t.Fatalf("got %v", err)
	}
}

func TestRestartRefusesUnidentifiedProcess(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(`{}`)) }))
	defer server.Close()
	previous := cdpAddress()
	setCDPAddress(server.URL)
	t.Cleanup(func() { setCDPAddress(previous) })
	if err := stopLocalChrome(); err == nil || !strings.Contains(err.Error(), "identify") {
		t.Fatalf("got %v", err)
	}
}

func TestRecoverySnapshotIsPrivateAndProfileBound(t *testing.T) {
	fake := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/json/version" {
			_, _ = w.Write([]byte(`{"webSocketDebuggerUrl":"ws://fixture/devtools/browser/snapshot"}`))
		} else {
			_, _ = w.Write([]byte(`[]`))
		}
	}))
	defer fake.Close()
	previous := cdpAddress()
	setCDPAddress(fake.URL)
	defer setCDPAddress(previous)
	InitConfig(t.TempDir())
	t.Cleanup(func() { cfgStore.mu.Lock(); cfgStore.file, cfgStore.portFile = "", ""; cfgStore.mu.Unlock() })
	urls := []string{"https://example.com/#/one", "https://example.com/#/two"}
	rememberRecoveryURLs(urls)
	if got := savedRecoveryURLs(); len(got) != 2 || got[0] != urls[0] {
		t.Fatalf("got %v", got)
	}
	info, err := os.Stat(recoveryFile())
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("permissions: %v %v", info, err)
	}
	off := false
	if err := saveConfig(Config{Profile: "/a/different/profile", AutoRecover: &off}); err != nil {
		t.Fatal(err)
	}
	if savedRecoveryURLs() != nil {
		t.Fatal("restored tabs from another profile")
	}
	if *effectiveConfig().AutoRecover {
		t.Fatal("ignored recovery opt-out")
	}
}

func TestRendererProbeAcceptsReplyAndHonorsDeadline(t *testing.T) {
	for _, responds := range []bool{true, false} {
		t.Run(map[bool]string{true: "healthy", false: "hung"}[responds], func(t *testing.T) {
			upgrader := websocket.Upgrader{}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				conn, err := upgrader.Upgrade(w, r, nil)
				if err != nil {
					return
				}
				defer conn.Close()
				var request map[string]any
				if conn.ReadJSON(&request) != nil {
					return
				}
				if responds {
					_ = conn.WriteJSON(map[string]any{"id": request["id"], "result": map[string]any{}})
				}
				_, _, _ = conn.ReadMessage()
			}))
			defer server.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
			defer cancel()
			if got := pageResponds(ctx, target{WebSocketDebuggerURL: "ws" + strings.TrimPrefix(server.URL, "http")}); got != responds {
				t.Fatalf("got %v", got)
			}
		})
	}
}

func TestRecoveryBindsOriginsToCreatedTargetsDespiteDuplicateURLs(t *testing.T) {
	InitConfig(t.TempDir())
	t.Cleanup(func() { cfgStore.mu.Lock(); cfgStore.file, cfgStore.portFile = "", ""; cfgStore.mu.Unlock() })
	pages := []target{{ID: "existing", Type: "page", URL: "https://same.example"}}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/json/version":
			_, _ = w.Write([]byte(`{"webSocketDebuggerUrl":"ws://fixture/devtools/browser/replacement"}`))
		case "/json":
			_ = json.NewEncoder(w).Encode(pages)
		case "/json/new":
			page := target{ID: "restored-" + strconv.Itoa(len(pages)), Type: "page", URL: "https://same.example"}
			pages = append([]target{page}, pages...)
			_ = json.NewEncoder(w).Encode(page)
		default:
			_, _ = w.Write([]byte("ok"))
		}
	}))
	defer server.Close()
	old := cdpAddress()
	setCDPAddress(server.URL)
	defer setCDPAddress(old)
	if _, err := tabCatalog(browsertabs.Event{Action: "create", BrowserID: "replacement", TargetID: "existing", Origin: "human"}); err != nil {
		t.Fatal(err)
	}
	origins := []recoveryTab{{URL: "https://same.example", Origin: "human", CreatedBy: "agent", Pinned: true}, {URL: "https://same.example", Origin: "agent", CreatedBy: "human"}}
	if _, err := restoreTabs([]string{origins[0].URL, origins[1].URL}, origins); err != nil {
		t.Fatal(err)
	}
	result, err := tabCatalog(browsertabs.Event{Action: "sync", BrowserID: "replacement", Targets: []string{"existing", "restored-1", "restored-2"}})
	if err != nil {
		t.Fatal(err)
	}
	if result.Entries["existing"].CreatedBy != "human" || result.Entries["existing"].Origin != "human" {
		t.Fatal("overwrote an existing page")
	}
	if result.Entries["restored-1"].CreatedBy != "agent" || !result.Entries["restored-1"].Pinned || result.Entries["restored-1"].Origin != "human" {
		t.Fatal("lost first snapshot origin")
	}
	if result.Entries["restored-2"].CreatedBy != "human" || result.Entries["restored-2"].Origin != "agent" {
		t.Fatal("mixed origins by URL order")
	}
}
