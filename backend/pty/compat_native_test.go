package pty

import (
	"context"
	"net/http/httptest"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionhost"
)

func TestNativeSinglePaneWebSocketDirectAndLayoutNotify(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix shell integration test")
	}
	gin.SetMode(gin.TestMode)
	host := sessionhost.NewHost(sessionhost.Config{HostID: "test-host-ws", LogsDir: t.TempDir()})
	t.Cleanup(func() { host.Shutdown(context.Background()) })

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	ref, err := host.Create(ctx, sessionbackend.CreateSpec{
		SessionID: "single-pane-ws",
		Exe:       "/bin/sh",
		Cols:      80,
		Rows:      24,
	})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	r := gin.New()
	r.GET("/api/term/:name", HandlerWithNative(host))
	srv := httptest.NewServer(r)
	defer srv.Close()

	wsURL := "ws" + strings.TrimPrefix(srv.URL, "http") + "/api/term/" + ref.SessionID + "?pane=" + ref.PaneID + "&cols=80&rows=24"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("dial ws: %v", err)
	}
	defer conn.Close()

	// Write a marker command directly to this independent pane.
	if err := conn.WriteMessage(websocket.TextMessage, []byte("echo DIRECT_PANE_OK\n")); err != nil {
		t.Fatalf("write input: %v", err)
	}

	gotOutput := false
	gotLayout := false
	notified := false
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) && (!gotOutput || !gotLayout) {
		_ = conn.SetReadDeadline(time.Now().Add(2 * time.Second))
		mt, data, err := conn.ReadMessage()
		if err != nil {
			t.Fatalf("read ws: %v (gotOutput=%v gotLayout=%v)", err, gotOutput, gotLayout)
		}
		text := string(data)
		if mt == websocket.BinaryMessage {
			if strings.Contains(text, "F2:菜单") || strings.Contains(text, "F2 / Ctrl+b") {
				t.Fatalf("unexpected CLI status bar leaked into Web single-pane stream: %q", text)
			}
			if strings.Contains(text, "DIRECT_PANE_OK") {
				gotOutput = true
				if !notified {
					notified = true
					NotifyNativeLayout(ref.SessionID, ref.PaneID)
				}
			}
		} else if mt == websocket.TextMessage && strings.Contains(text, `"type":"layout"`) {
			gotLayout = true
		}
	}
	if !gotOutput {
		t.Fatalf("did not receive direct pane output")
	}
	if !gotLayout {
		t.Fatalf("did not receive layout change text frame")
	}
}
