package pty

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/cli/nativeattach"
	"github.com/ybz21/Roami/internal/sessionbackend"
)

var (
	nativeLayoutMu   sync.RWMutex
	nativeLayoutSubs = map[string]map[chan string]struct{}{}
)

func subscribeNativeLayout(sessionID string) (chan string, func()) {
	ch := make(chan string, 4)
	nativeLayoutMu.Lock()
	if nativeLayoutSubs[sessionID] == nil {
		nativeLayoutSubs[sessionID] = map[chan string]struct{}{}
	}
	nativeLayoutSubs[sessionID][ch] = struct{}{}
	nativeLayoutMu.Unlock()
	return ch, func() {
		nativeLayoutMu.Lock()
		if set := nativeLayoutSubs[sessionID]; set != nil {
			delete(set, ch)
			if len(set) == 0 {
				delete(nativeLayoutSubs, sessionID)
			}
		}
		nativeLayoutMu.Unlock()
	}
}

// NotifyNativeLayout wakes all live WebSocket terminal attachments for sessionID after a
// REST layout mutation (window switch/create/close, split, focus, close-pane) so screens
// update immediately even if an older roami-term does not broadcast window switch events.
func NotifyNativeLayout(sessionID, activePaneID string) {
	nativeLayoutMu.RLock()
	set := nativeLayoutSubs[sessionID]
	chans := make([]chan string, 0, len(set))
	for ch := range set {
		chans = append(chans, ch)
	}
	nativeLayoutMu.RUnlock()
	for _, ch := range chans {
		select {
		case ch <- activePaneID:
		default:
			select {
			case <-ch:
			default:
			}
			select {
			case ch <- activePaneID:
			default:
			}
		}
	}
}

// HandlerWithNative serves /api/term/:name, transparently bridging native roami-term
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

type wsBinaryWriter struct {
	writeMessage func(int, []byte) error
}

func (w *wsBinaryWriter) Write(p []byte) (int, error) {
	if len(p) == 0 {
		return 0, nil
	}
	cp := make([]byte, len(p))
	copy(cp, p)
	if err := w.writeMessage(websocket.BinaryMessage, cp); err != nil {
		return 0, err
	}
	return len(p), nil
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
	if paneID != "" {
		serveNativeSinglePaneWS(ctx, cancel, conn, backend, name, paneID, c.Query("clientId"), c.ClientIP(), c.Query("cols"), c.Query("rows"))
		return
	}
	paneID = initial.ActivePaneID
	clientID := c.Query("clientId")
	if clientID == "" {
		clientID = fmt.Sprintf("web-%s-%d", c.ClientIP(), time.Now().UnixNano())
	}

	lastCols, lastRows := uint16(100), uint16(30)
	if cl, err := strconv.Atoi(c.Query("cols")); err == nil && cl >= minCols && cl <= 1000 {
		lastCols = uint16(cl)
	}
	if r, err := strconv.Atoi(c.Query("rows")); err == nil && r >= minRows && r <= 500 {
		lastRows = uint16(r)
	}

	var writeMu sync.Mutex
	writeMessage := func(messageType int, data []byte) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteMessage(messageType, data)
	}

	var paneMu sync.RWMutex
	var lastMode sessionbackend.TerminalMode
	setActivePane := func(_ string) {
		paneMu.Lock()
		lastMode = sessionbackend.TerminalMode{}
		paneMu.Unlock()
	}
	setMode := func(m sessionbackend.TerminalMode) {
		paneMu.Lock()
		lastMode = m
		paneMu.Unlock()
	}
	getMode := func() sessionbackend.TerminalMode {
		paneMu.RLock()
		defer paneMu.RUnlock()
		return lastMode
	}

	inR, inW := io.Pipe()
	defer inW.Close()

	resizeCh := make(chan [2]uint16, 4)
	selectCellCh := make(chan [2]int, 4)
	moveCursorCh := make(chan [2]int, 4)
	switchPaneCh, unsubscribeLayout := subscribeNativeLayout(name)
	defer unsubscribeLayout()
	showBar := false
	layoutBackend, _ := backend.(sessionbackend.LayoutBackend)

	initCols, initRows := lastCols, lastRows
	// Fallback when ?pane= is omitted: reuse nativeattach without the bottom ANSI status bar.
	go func() {
		defer cancel()
		_ = nativeattach.Attach(ctx, backend, layoutBackend, nativeattach.AttachOptions{
			SessionID:     name,
			PaneID:        paneID,
			ClientID:      clientID,
			In:            inR,
			Out:           &wsBinaryWriter{writeMessage: writeMessage},
			ShowStatusBar: &showBar,
			ResizeCh:      resizeCh,
			SelectCellCh:  selectCellCh,
			MoveCursorCh:  moveCursorCh,
			SwitchPaneCh:  switchPaneCh,
			OnActivePane:  setActivePane,
			OnMode:        setMode,
			Cols:          initCols,
			Rows:          initRows,
		})
		_ = writeMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
		_ = conn.Close()
	}()

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
					select {
					case resizeCh <- [2]uint16{ctrl.Cols, ctrl.Rows}:
					default:
						select {
						case <-resizeCh:
						default:
						}
						resizeCh <- [2]uint16{ctrl.Cols, ctrl.Rows}
					}
					continue
				case "select-pane":
					select {
					case selectCellCh <- [2]int{ctrl.Col, ctrl.Row}:
					default:
					}
					continue
				case "move-cursor":
					select {
					case moveCursorCh <- [2]int{ctrl.Col, ctrl.Row}:
					default:
					}
					continue
				case "scroll":
					m := getMode()
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
						_, _ = inW.Write(buf)
					}
					continue
				}
			}
		}
		if _, err := inW.Write(data); err != nil {
			return
		}
	}
}

// serveNativeSinglePaneWS binds one WebSocket 1:1 to a single native pane with zero character-grid
// compositing and zero ANSI status bar, so Roami's DOM SplitTree owns layout while each xterm.js
// instance keeps native multi-line selection, select-all, copy, and independent scrollback.
func serveNativeSinglePaneWS(
	ctx context.Context,
	cancel context.CancelFunc,
	conn *websocket.Conn,
	backend sessionbackend.SessionBackend,
	sessionID, paneID, clientID, clientIP, colsQ, rowsQ string,
) {
	if clientID == "" {
		clientID = fmt.Sprintf("web-%s-%s-%d", clientIP, paneID, time.Now().UnixNano())
	}
	cols, rows := uint16(100), uint16(30)
	if cl, err := strconv.Atoi(colsQ); err == nil && cl >= minCols && cl <= 1000 {
		cols = uint16(cl)
	}
	if r, err := strconv.Atoi(rowsQ); err == nil && r >= minRows && r <= 500 {
		rows = uint16(r)
	}

	var writeMu sync.Mutex
	writeMessage := func(messageType int, data []byte) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		return conn.WriteMessage(messageType, data)
	}

	target := sessionbackend.Target{SessionID: sessionID, PaneID: paneID}
	lease, err := backend.ClaimControl(ctx, target, clientID)
	if err != nil {
		_ = writeMessage(websocket.CloseMessage, websocket.FormatCloseMessage(closeSessionGone, "pane gone"))
		return
	}
	var ctrlMu sync.Mutex
	controlGen := lease.ControlGen
	controlLost := false
	lastCols, lastRows := cols, rows
	var lastMode atomic.Value
	lastMode.Store(sessionbackend.TerminalMode{})

	defer func() {
		ctrlMu.Lock()
		g := controlGen
		ctrlMu.Unlock()
		if g > 0 {
			_ = backend.ReleaseControl(context.Background(), target, clientID, g)
		}
	}()

	_ = backend.Resize(ctx, target, controlGen, cols, rows)
	stream, err := backend.Attach(ctx, target, sessionbackend.AttachOpts{ClientID: clientID})
	if err != nil {
		_ = writeMessage(websocket.CloseMessage, websocket.FormatCloseMessage(closeSessionGone, "pane gone"))
		return
	}
	defer stream.Close()

	reclaimAndResize := func(c, r uint16) uint64 {
		newLease, lerr := backend.ClaimControl(ctx, target, clientID)
		if lerr != nil {
			ctrlMu.Lock()
			g := controlGen
			ctrlMu.Unlock()
			return g
		}
		ctrlMu.Lock()
		controlGen = newLease.ControlGen
		controlLost = false
		if c >= minCols && r >= minRows {
			lastCols, lastRows = c, r
		}
		c, r = lastCols, lastRows
		g := controlGen
		ctrlMu.Unlock()
		_ = backend.Resize(ctx, target, g, c, r)
		return g
	}

	writePaneInput := func(raw []byte) error {
		cleaned := nativeattach.FilterAutoReplies(raw)
		if len(cleaned) == 0 {
			return nil
		}
		ctrlMu.Lock()
		lost := controlLost
		g := controlGen
		c, r := lastCols, lastRows
		ctrlMu.Unlock()
		if lost {
			g = reclaimAndResize(c, r)
		}
		werr := backend.WriteInput(ctx, target, g, cleaned)
		if errors.Is(werr, sessionbackend.ErrStaleControl) {
			g = reclaimAndResize(c, r)
			werr = backend.WriteInput(ctx, target, g, cleaned)
		}
		return werr
	}

	layoutCh, unsubLayout := subscribeNativeLayout(sessionID)
	defer unsubLayout()

	sendLayoutNotice := func() error {
		return writeMessage(websocket.TextMessage, []byte(`{"type":"layout"}`))
	}

	// Stream PTY output + layout change notices -> WebSocket.
	go func() {
		defer cancel()
		for {
			select {
			case <-ctx.Done():
				return
			case _, ok := <-layoutCh:
				if !ok {
					layoutCh = nil
					continue
				}
				if err := sendLayoutNotice(); err != nil {
					return
				}
			case ev, ok := <-stream.Events():
				if !ok {
					_ = sendLayoutNotice()
					_ = writeMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
					_ = conn.Close()
					return
				}
				if ev.Mode != nil {
					lastMode.Store(*ev.Mode)
				}
				switch ev.Kind {
				case sessionbackend.EventControl:
					ctrlMu.Lock()
					if (ev.Controller != "" && ev.Controller != clientID) || ev.ControlGen > controlGen {
						controlLost = true
					}
					ctrlMu.Unlock()
				case sessionbackend.EventSnapshot:
					buf := make([]byte, 0, 7+len(ev.Data))
					buf = append(buf, "\x1b[2J\x1b[H"...)
					buf = append(buf, ev.Data...)
					if err := writeMessage(websocket.BinaryMessage, buf); err != nil {
						return
					}
				case sessionbackend.EventOutput:
					if len(ev.Data) > 0 {
						if err := writeMessage(websocket.BinaryMessage, ev.Data); err != nil {
							return
						}
					}
				case sessionbackend.EventLayoutChanged:
					if err := sendLayoutNotice(); err != nil {
						return
					}
				case sessionbackend.EventExited:
					_ = sendLayoutNotice()
					_ = writeMessage(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
					_ = conn.Close()
					return
				}
			}
		}
	}()

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
					ctrlMu.Lock()
					same := ctrl.Cols == lastCols && ctrl.Rows == lastRows && !controlLost
					if !same {
						lastCols, lastRows = ctrl.Cols, ctrl.Rows
					}
					lost := controlLost
					g := controlGen
					ctrlMu.Unlock()
					if same {
						continue
					}
					if lost {
						reclaimAndResize(ctrl.Cols, ctrl.Rows)
					} else if rerr := backend.Resize(ctx, target, g, ctrl.Cols, ctrl.Rows); errors.Is(rerr, sessionbackend.ErrStaleControl) {
						reclaimAndResize(ctrl.Cols, ctrl.Rows)
					}
					continue
				case "select-pane", "focus":
					ctrlMu.Lock()
					lost := controlLost
					c, r := lastCols, lastRows
					ctrlMu.Unlock()
					if lost {
						reclaimAndResize(c, r)
					}
					continue
				case "move-cursor":
					ctrlMu.Lock()
					lost := controlLost
					g := controlGen
					c, r := lastCols, lastRows
					ctrlMu.Unlock()
					if lost {
						reclaimAndResize(c, r)
						continue
					}
					_ = backend.MoveCursor(ctx, target, g, ctrl.Col, ctrl.Row)
					continue
				case "scroll":
					m, _ := lastMode.Load().(sessionbackend.TerminalMode)
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
						_ = writePaneInput(buf)
					}
					continue
				}
			}
		}
		if err := writePaneInput(data); err != nil {
			return
		}
	}
}
