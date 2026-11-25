package pty

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"strconv"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/gorilla/websocket"
	"github.com/ybz21/Roami/internal/cli/nativeattach"
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
	if paneID == "" {
		paneID = initial.ActivePaneID
	}
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
	activePane := paneID
	var lastMode sessionbackend.TerminalMode
	setActivePane := func(pid string) {
		paneMu.Lock()
		activePane = pid
		lastMode = sessionbackend.TerminalMode{}
		paneMu.Unlock()
	}
	getActivePane := func() string {
		paneMu.RLock()
		defer paneMu.RUnlock()
		return activePane
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
	showBar := true
	layoutBackend, _ := backend.(sessionbackend.LayoutBackend)

	// Reuse nativeattach so Web xterm.js gets the exact same multi-pane splits, bottom status bar,
	// interactive Ctrl+b m menu, and Ctrl+b w window switcher as CLI attach.
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
			OnActivePane:  setActivePane,
			OnMode:        setMode,
			Cols:          lastCols,
			Rows:          lastRows,
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
					target := sessionbackend.Target{SessionID: name, PaneID: getActivePane()}
					if lease, lerr := backend.ClaimControl(ctx, target, clientID); lerr == nil {
						_ = backend.MoveCursor(ctx, target, lease.ControlGen, ctrl.Col, ctrl.Row)
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
