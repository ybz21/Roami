package pty

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"net/http"
	"strconv"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/sessionbackend"
)

type nativeControlMsg struct {
	Type            string                  `json:"type"`
	ID              string                  `json:"id,omitempty"`
	RequestID       string                  `json:"requestId,omitempty"`
	PaneID          string                  `json:"paneId,omitempty"`
	WindowID        string                  `json:"windowId,omitempty"`
	NodeID          string                  `json:"nodeId,omitempty"`
	ControlGen      uint64                  `json:"controlGen,omitempty"`
	Cols            uint16                  `json:"cols,omitempty"`
	Rows            uint16                  `json:"rows,omitempty"`
	Col             int                     `json:"col,omitempty"`
	Row             int                     `json:"row,omitempty"`
	Data            string                  `json:"data,omitempty"`
	SubmitEnter     bool                    `json:"submitEnter,omitempty"`
	BracketedPaste  bool                    `json:"bracketedPaste,omitempty"`
	Dir             sessionbackend.SplitDir `json:"dir,omitempty"`
	Ratio           float64                 `json:"ratio,omitempty"`
	ExpectedVersion int64                   `json:"expectedVersion,omitempty"`
	LastSeq         uint64                  `json:"lastSeq,omitempty"`
}

// NativeHandler bridges WebSocket clients to a native SessionBackend (roami-sessiond) using
// 8-byte big-endian sequenced binary output frames and JSON control/layout frames.
func NativeHandler(backend sessionbackend.SessionBackend) gin.HandlerFunc {
	return func(c *gin.Context) {
		if backend == nil {
			c.AbortWithStatus(http.StatusServiceUnavailable)
			return
		}
		sessionID := SanitizeSessionName(c.Param("name"))
		paneID := c.Query("pane")
		clientID := c.Query("clientId")
		if clientID == "" {
			clientID = "ws-" + c.ClientIP()
		}
		var lastSeq uint64
		if raw := c.Query("lastSeq"); raw != "" {
			lastSeq, _ = strconv.ParseUint(raw, 10, 64)
		}
		readOnly := c.Query("readonly") == "1"

		conn, err := upgrader.Upgrade(c.Writer, c.Request, nil)
		if err != nil {
			return
		}
		defer conn.Close()

		ctx, cancel := context.WithCancel(c.Request.Context())
		defer cancel()

		target := sessionbackend.Target{SessionID: sessionID, PaneID: paneID}
		stream, err := backend.Attach(ctx, target, sessionbackend.AttachOpts{
			LastSeq:  lastSeq,
			ReadOnly: readOnly,
			ClientID: clientID,
		})
		if err != nil {
			_ = conn.WriteMessage(websocket.CloseMessage, websocket.FormatCloseMessage(closeSessionGone, "session gone"))
			return
		}
		defer stream.Close()

		var writeMu sync.Mutex
		writeMsg := func(mt int, payload []byte) error {
			writeMu.Lock()
			defer writeMu.Unlock()
			return conn.WriteMessage(mt, payload)
		}
		writeJSON := func(v any) error {
			raw, err := json.Marshal(v)
			if err != nil {
				return err
			}
			return writeMsg(websocket.TextMessage, raw)
		}

		// Stream events -> WebSocket (binary frames carry 8-byte big-endian seq + raw VT bytes).
		go func() {
			defer cancel()
			for ev := range stream.Events() {
				if ev.Kind == sessionbackend.EventOutput {
					frame := make([]byte, 8+len(ev.Data))
					binary.BigEndian.PutUint64(frame[:8], ev.Seq)
					copy(frame[8:], ev.Data)
					if err := writeMsg(websocket.BinaryMessage, frame); err != nil {
						return
					}
					continue
				}
				msg := map[string]any{
					"type":       string(ev.Kind),
					"seq":        ev.Seq,
					"paneId":     ev.PaneID,
					"paneGen":    ev.PaneGen,
					"controlGen": ev.ControlGen,
					"controller": ev.Controller,
				}
				if ev.Kind == sessionbackend.EventSnapshot {
					msg["data"] = string(ev.Data)
				}
				if ev.Mode != nil {
					msg["mode"] = ev.Mode
				}
				if ev.Window != nil {
					msg["window"] = ev.Window
				}
				if ev.ExitCode != nil {
					msg["exitCode"] = *ev.ExitCode
					msg["signal"] = ev.Signal
					msg["drained"] = ev.Drained
				}
				if err := writeJSON(msg); err != nil {
					return
				}
			}
		}()

		var activeControlGen uint64
		for {
			mt, data, err := conn.ReadMessage()
			if err != nil {
				return
			}
			if mt == websocket.TextMessage && len(data) > 0 && data[0] == '{' {
				var ctrl nativeControlMsg
				if json.Unmarshal(data, &ctrl) == nil && ctrl.Type != "" {
					t := target
					if ctrl.PaneID != "" {
						t.PaneID = ctrl.PaneID
					}
					if ctrl.WindowID != "" {
						t.WindowID = ctrl.WindowID
					}
					cgen := ctrl.ControlGen
					if cgen == 0 {
						cgen = activeControlGen
					}
					switch ctrl.Type {
					case "ping":
						_ = writeJSON(map[string]any{"type": "pong", "id": ctrl.ID})
						continue
					case "claim":
						if readOnly {
							_ = writeJSON(map[string]any{"type": "error", "id": ctrl.ID, "code": "READ_ONLY"})
							continue
						}
						lease, err := backend.ClaimControl(ctx, t, clientID)
						if err != nil {
							_ = writeJSON(map[string]any{"type": "error", "id": ctrl.ID, "error": err.Error()})
							continue
						}
						activeControlGen = lease.ControlGen
						_ = writeJSON(map[string]any{"type": "claimed", "id": ctrl.ID, "lease": lease})
						continue
					case "release":
						_ = backend.ReleaseControl(ctx, t, clientID, cgen)
						activeControlGen = 0
						continue
					case "input":
						if !readOnly {
							_ = backend.WriteInput(ctx, t, cgen, []byte(ctrl.Data))
						}
						continue
					case "submit":
						if readOnly {
							continue
						}
						rec, err := backend.Submit(ctx, t, sessionbackend.SubmitReq{
							RequestID:      ctrl.RequestID,
							Payload:        ctrl.Data,
							SubmitEnter:    ctrl.SubmitEnter,
							BracketedPaste: ctrl.BracketedPaste,
						})
						if err != nil {
							_ = writeJSON(map[string]any{"type": "error", "id": ctrl.ID, "error": err.Error()})
						} else {
							_ = writeJSON(map[string]any{"type": "submitted", "id": ctrl.ID, "receipt": rec})
						}
						continue
					case "resize":
						if !readOnly {
							_ = backend.Resize(ctx, t, cgen, ctrl.Cols, ctrl.Rows)
						}
						continue
					case "move-cursor":
						if !readOnly {
							_ = backend.MoveCursor(ctx, t, cgen, ctrl.Col, ctrl.Row)
						}
						continue
					case "split":
						if lb, ok := backend.(sessionbackend.LayoutBackend); ok && !readOnly {
							win, newPaneID, err := lb.SplitPane(ctx, sessionID, t.PaneID, sessionbackend.SplitSpec{
								Dir: ctrl.Dir, Ratio: ctrl.Ratio,
							})
							if err != nil {
								_ = writeJSON(map[string]any{"type": "error", "id": ctrl.ID, "error": err.Error()})
							} else {
								_ = writeJSON(map[string]any{"type": "split_ok", "id": ctrl.ID, "window": win, "paneId": newPaneID})
							}
						}
						continue
					case "resize-split":
						if lb, ok := backend.(sessionbackend.LayoutBackend); ok && !readOnly {
							win, err := lb.ResizeSplit(ctx, sessionID, ctrl.WindowID, ctrl.NodeID, ctrl.Ratio, ctrl.ExpectedVersion)
							if err != nil {
								_ = writeJSON(map[string]any{"type": "error", "id": ctrl.ID, "error": err.Error()})
							} else {
								_ = writeJSON(map[string]any{"type": "layout_changed", "id": ctrl.ID, "window": win})
							}
						}
						continue
					case "focus-pane":
						if lb, ok := backend.(sessionbackend.LayoutBackend); ok {
							_, _ = lb.FocusPane(ctx, sessionID, ctrl.WindowID, t.PaneID)
						}
						continue
					case "close-pane":
						if lb, ok := backend.(sessionbackend.LayoutBackend); ok && !readOnly {
							_, _ = lb.ClosePane(ctx, sessionID, t.PaneID)
						}
						continue
					}
				}
			}
			if !readOnly {
				_ = backend.WriteInput(ctx, target, activeControlGen, data)
			}
		}
	}
}
