package pty

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/sessionbackend"
)

// HandlerWithNative serves /api/term/:name, transparently bridging native roami-sessiond
// sessions using the legacy xterm.js wire protocol (raw binary VT bytes + JSON control frames)
// while delegating tmux sessions to the existing Handler unchanged.
func HandlerWithNative(nativeBackend sessionbackend.SessionBackend) gin.HandlerFunc {
	if nativeBackend == nil {
		return Handler
	}
	return func(c *gin.Context) {
		name := SanitizeSessionName(c.Param("name"))
		obsCtx, cancel := context.WithTimeout(c.Request.Context(), 3*time.Second)
		st, err := nativeBackend.Observe(obsCtx, name)
		cancel()
		if err != nil || st.Backend != sessionbackend.BackendNative {
			Handler(c)
			return
		}
		serveNativeCompatWS(c, nativeBackend, name, st)
	}
}

func serveNativeCompatWS(c *gin.Context, backend sessionbackend.SessionBackend, name string, initial sessionbackend.SessionState) {
	conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
	if err != nil {
		return
	}
	defer conn.Close()

	ctx, cancel := context.WithCancel(c.Request.Context())
	defer cancel()

	paneID := c.Query("pane")
	if paneID == "" {
		paneID = initial.ActivePaneID
	}
	clientID := c.Query("clientId")
	if clientID == "" {
		clientID = fmt.Sprintf("web-%s-%d", c.ClientIP(), time.Now().UnixNano())
	}
	target := sessionbackend.Target{SessionID: name, PaneID: paneID}

	lease, err := backend.ClaimControl(ctx, target, clientID)
	if err != nil {
		_ = conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(closeSessionGone, "session gone"))
		return
	}
	controlGen := lease.ControlGen
	if lease.PaneID != "" {
		target.PaneID = lease.PaneID
	}
	defer func() {
		_ = backend.ReleaseControl(context.Background(), target, clientID, controlGen)
	}()

	lastCols, lastRows := uint16(100), uint16(30)
	if cl, err := strconv.Atoi(c.Query("cols")); err == nil && cl >= minCols && cl <= 1000 {
		lastCols = uint16(cl)
	}
	if r, err := strconv.Atoi(c.Query("rows")); err == nil && r >= minRows && r <= 500 {
		lastRows = uint16(r)
	}
	_ = backend.Resize(ctx, target, controlGen, lastCols, lastRows)

	stream, err := backend.Attach(ctx, target, sessionbackend.AttachOpts{ClientID: clientID})
	if err != nil {
		_ = conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(closeSessionGone, "session gone"))
		return
	}
	defer stream.Close()

	var writeMu sync.Mutex
	writeMessage := func(messageType int, data []byte) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteMessage(messageType, data)
	}

	var modeMu sync.RWMutex
	var lastMode sessionbackend.TerminalMode

	// Host stream -> xterm.js WebSocket (raw binary bytes, matching tmux pty.Handler).
	go func() {
		defer cancel()
		for ev := range stream.Events() {
			if ev.Mode != nil {
				modeMu.Lock()
				lastMode = *ev.Mode
				modeMu.Unlock()
			}
			switch ev.Kind {
			case sessionbackend.EventSnapshot:
				payload := make([]byte, 0, 7+len(ev.Data))
				payload = append(payload, "\x1b[2J\x1b[H"...)
				payload = append(payload, ev.Data...)
				if werr := writeMessage(websocket.BinaryMessage, payload); werr != nil {
					return
				}
			case sessionbackend.EventOutput:
				if len(ev.Data) > 0 {
					if werr := writeMessage(websocket.BinaryMessage, ev.Data); werr != nil {
						return
					}
				}
			case sessionbackend.EventExited:
				_ = writeMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
				_ = conn.Close()
				return
			}
		}
		_ = writeMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
		_ = conn.Close()
	}()

	writeInput := func(data []byte) error {
		werr := backend.WriteInput(ctx, target, controlGen, data)
		if errors.Is(werr, sessionbackend.ErrStaleControl) {
			if next, cerr := backend.ClaimControl(ctx, target, clientID); cerr == nil {
				controlGen = next.ControlGen
				werr = backend.WriteInput(ctx, target, controlGen, data)
			}
		}
		return werr
	}

	for {
		mt, data, err := conn.ReadMessage()
		if err != nil {
			return
		}
		if mt == websocket.TextMessage && len(data) > 0 && data[0] == '{' {
			var ctrl struct {
				Type  string `json:"type"`
				Cols  uint16 `json:"cols"`
				Rows  uint16 `json:"rows"`
				Dir   string `json:"dir"`
				Lines int    `json:"lines"`
				Col   int    `json:"col"`
				Row   int    `json:"row"`
				ID    string `json:"id"`
			}
			if json.Unmarshal(data, &ctrl) == nil && ctrl.Type != "" {
				switch ctrl.Type {
				case "ping":
					pong, _ := json.Marshal(struct {
						Type string `json:"type"`
						ID   string `json:"id"`
					}{Type: "pong", ID: ctrl.ID})
					if werr := writeMessage(websocket.TextMessage, pong); werr != nil {
						return
					}
					continue
				case "resize":
					if ctrl.Cols < minCols || ctrl.Rows < minRows {
						continue
					}
					if ctrl.Cols == lastCols && ctrl.Rows == lastRows {
						continue
					}
					lastCols, lastRows = ctrl.Cols, ctrl.Rows
					rerr := backend.Resize(ctx, target, controlGen, ctrl.Cols, ctrl.Rows)
					if errors.Is(rerr, sessionbackend.ErrStaleControl) {
						if next, cerr := backend.ClaimControl(ctx, target, clientID); cerr == nil {
							controlGen = next.ControlGen
							_ = backend.Resize(ctx, target, controlGen, ctrl.Cols, ctrl.Rows)
						}
					}
					continue
				case "move-cursor":
					_ = backend.MoveCursor(ctx, target, controlGen, ctrl.Col, ctrl.Row)
					continue
				case "scroll":
					modeMu.RLock()
					m := lastMode
					modeMu.RUnlock()
					if m.AltScreen && m.MouseOn && (ctrl.Dir == "up" || ctrl.Dir == "down") {
						lines := ctrl.Lines
						if lines <= 0 {
							lines = 1
						}
						if lines > maxWheelNotches {
							lines = maxWheelNotches
						}
						btn := 64
						if ctrl.Dir != "up" {
							btn = 65
						}
						col, row := int(m.Cols)/2, int(m.Rows)/2
						if col < 1 {
							col = 1
						}
						if row < 1 {
							row = 1
						}
						var seq string
						if m.MouseSGR {
							seq = fmt.Sprintf("\x1b[<%d;%d;%dM", btn, col, row)
						} else {
							seq = fmt.Sprintf("\x1b[M%c%c%c", rune(32+btn), rune(32+min(col, 223)), rune(32+min(row, 223)))
						}
						buf := make([]byte, 0, len(seq)*lines)
						for i := 0; i < lines; i++ {
							buf = append(buf, seq...)
						}
						_ = writeInput(buf)
					}
					continue
				case "select-pane":
					continue
				}
			}
		}
		if err := writeInput(data); err != nil {
			return
		}
	}
}
