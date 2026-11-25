package pty

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"net/http/httptest"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionhost"
	"github.com/ybz21/Roami/internal/sessionipc"
)

func TestNativeWebSocketBridgeEndToEnd(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	root := t.TempDir()
	host := sessionhost.NewHost(sessionhost.Config{
		HostID:  "ws-host-1",
		LogsDir: filepath.Join(root, "logs"),
	})
	defer host.Shutdown(ctx)

	ipcSrv, err := sessionipc.NewServer(host, root)
	if err != nil {
		t.Fatal(err)
	}
	defer ipcSrv.Close()
	go func() { _ = ipcSrv.Serve(ctx) }()

	client, err := sessionipc.Dial(ctx, ipcSrv.Descriptor())
	if err != nil {
		t.Fatal(err)
	}
	defer client.CloseConn()

	ref, err := client.Create(ctx, sessionbackend.CreateSpec{
		Label: "ws-demo",
		Exe:   "/bin/sh",
		Env:   []string{"ROAMI_WS_OK=42"},
		Cols:  80,
		Rows:  24,
	})
	if err != nil {
		t.Fatal(err)
	}

	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/api/term/native/:name", NativeHandler(client))
	ts := httptest.NewServer(r)
	defer ts.Close()

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/api/term/native/" + ref.SessionID + "?clientId=browser-1"
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("ws dial failed: %v", err)
	}
	defer ws.Close()

	// 1. Expect initial snapshot control frame.
	mt, raw, err := ws.ReadMessage()
	if err != nil || mt != websocket.TextMessage {
		t.Fatalf("expected snapshot text frame, mt=%d err=%v", mt, err)
	}
	var snap struct {
		Type string `json:"type"`
		Seq  uint64 `json:"seq"`
	}
	if err := json.Unmarshal(raw, &snap); err != nil || snap.Type != "snapshot" {
		t.Fatalf("expected snapshot message, got %s", string(raw))
	}

	// 2. Claim control, send command, read sequenced binary output frame.
	_ = ws.WriteJSON(map[string]any{"type": "claim", "id": "c1"})
	_ = ws.WriteJSON(map[string]any{"type": "input", "data": "echo WS_VALUE_$ROAMI_WS_OK\n"})

	var outputBuf strings.Builder
	var lastSeq uint64
	_ = ws.SetReadDeadline(time.Now().Add(4 * time.Second))
	for !strings.Contains(outputBuf.String(), "WS_VALUE_42") {
		mt, data, err := ws.ReadMessage()
		if err != nil {
			t.Fatalf("timed out waiting for WS_VALUE_42; got %q err=%v", outputBuf.String(), err)
		}
		if mt == websocket.BinaryMessage && len(data) >= 8 {
			seq := binary.BigEndian.Uint64(data[:8])
			if seq <= lastSeq {
				t.Fatalf("non-monotonic binary frame seq: %d <= %d", seq, lastSeq)
			}
			lastSeq = seq
			outputBuf.Write(data[8:])
		}
	}

	// 3. Split vertically via WebSocket and verify split_ok + layout_changed!
	_ = ws.WriteJSON(map[string]any{"type": "split", "id": "sp1", "dir": "vertical", "ratio": 0.5})
	sawSplitOK := false
	_ = ws.SetReadDeadline(time.Now().Add(4 * time.Second))
	for !sawSplitOK {
		mt, data, err := ws.ReadMessage()
		if err != nil {
			t.Fatalf("waiting for split_ok failed: %v", err)
		}
		if mt == websocket.TextMessage {
			var msg map[string]any
			if json.Unmarshal(data, &msg) == nil && msg["type"] == "split_ok" {
				sawSplitOK = true
			}
		}
	}

	// 4. Close WS and reconnect with lastSeq -> incremental replay, session still alive!
	_ = ws.Close()
	ws2, _, err := websocket.DefaultDialer.Dial(wsURL+"&lastSeq="+strconv.FormatUint(lastSeq, 10), nil)
	if err != nil {
		t.Fatalf("ws2 reconnect failed: %v", err)
	}
	defer ws2.Close()

	st, err := client.Observe(ctx, ref.SessionID)
	if err != nil || st.Status != sessionbackend.StatusAlive || len(st.Windows[0].Layout.PaneIDs()) != 2 {
		t.Fatalf("expected alive 2-pane session after WS reconnect, got %+v err=%v", st, err)
	}
}

func TestHandlerWithNativeCompatWebSocket(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix shell integration test")
	}
	gin.SetMode(gin.TestMode)
	host := sessionhost.NewHost(sessionhost.Config{HostID: "compat-ws-host", LogsDir: t.TempDir()})
	defer host.Shutdown(context.Background())

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	ref, err := host.Create(ctx, sessionbackend.CreateSpec{
		SessionID: "compat-demo",
		Exe:       "/bin/sh",
		Cols:      80,
		Rows:      24,
	})
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}

	r := gin.New()
	r.GET("/api/term/:name", HandlerWithNative(host))
	ts := httptest.NewServer(r)
	defer ts.Close()

	wsURL := "ws" + strings.TrimPrefix(ts.URL, "http") + "/api/term/" + ref.SessionID + "?cols=100&rows=30"
	ws, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("compat WS dial failed: %v", err)
	}
	defer ws.Close()

	// Ping/pong and plain input matching Terminal.tsx wire protocol.
	_ = ws.WriteJSON(map[string]any{"type": "ping", "id": "p1"})
	_ = ws.WriteJSON(map[string]any{"type": "resize", "cols": 110, "rows": 32})
	_ = ws.WriteMessage(websocket.TextMessage, []byte("echo COMPAT_WEB_NATIVE_OK\n"))

	var out strings.Builder
	sawPong := false
	_ = ws.SetReadDeadline(time.Now().Add(5 * time.Second))
	for !sawPong || !strings.Contains(out.String(), "COMPAT_WEB_NATIVE_OK") {
		mt, data, err := ws.ReadMessage()
		if err != nil {
			t.Fatalf("compat WS read failed (pong=%v out=%q): %v", sawPong, out.String(), err)
		}
		if mt == websocket.TextMessage {
			var msg map[string]any
			if json.Unmarshal(data, &msg) == nil && msg["type"] == "pong" && msg["id"] == "p1" {
				sawPong = true
			}
		} else if mt == websocket.BinaryMessage {
			out.Write(data)
		}
	}
}
