// Package nativeattach implements the tmux-compatible CLI attach loop for native roami-sessiond panes.
package nativeattach

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/ttyraw"
)

const DefaultPrefix byte = 0x02 // Ctrl+b, matching tmux muscle memory.

const (
	// Restore scroll region, normal screen buffer, cursor visibility, mouse tracking, bracketed paste, and SGR attributes.
	terminalResetOnExit = "\x1b[r\x1b[?1049l\x1b[?25h\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[0m"
	clearScreenHome     = "\x1b[2J\x1b[H"
)

type ActionKind int

const (
	ActionForward ActionKind = iota
	ActionDetach
	ActionSplitH
	ActionSplitV
	ActionNextPane
	ActionClosePane
	ActionNewWindow
	ActionNextWindow
	ActionPrevWindow
	ActionSelectWindow
	ActionCloseWindow
	ActionOpenMenu
	ActionOpenWindowSwitcher
	ActionFocusLeft
	ActionFocusRight
	ActionFocusUp
	ActionFocusDown
)

type Action struct {
	Kind  ActionKind
	Data  []byte
	Index int // 1-based window index for ActionSelectWindow
}

type prefixState uint8

const (
	prefixIdle prefixState = iota
	prefixAwaitKey
	prefixAwaitEscBracket
	prefixAwaitCSI
)

// PrefixFilter intercepts tmux-style prefix key chords (Ctrl+b followed by
// d/m/?/w/c/n/p/1-9/%/"/o/x/& or arrow keys) while passing all other input untouched across chunk boundaries.
type PrefixFilter struct {
	Prefix byte
	state  prefixState
}

func NewPrefixFilter(prefix byte) *PrefixFilter {
	if prefix == 0 {
		prefix = DefaultPrefix
	}
	return &PrefixFilter{Prefix: prefix}
}

// Pending reports whether the prefix key was pressed and awaits the next command byte.
func (f *PrefixFilter) Pending() bool {
	return f.state != prefixIdle
}

func (f *PrefixFilter) Feed(chunk []byte) []Action {
	var actions []Action
	var buf []byte
	flush := func() {
		if len(buf) > 0 {
			cp := make([]byte, len(buf))
			copy(cp, buf)
			actions = append(actions, Action{Kind: ActionForward, Data: cp})
			buf = buf[:0]
		}
	}

	for _, b := range chunk {
		switch f.state {
		case prefixAwaitCSI:
			f.state = prefixIdle
			switch b {
			case 'A':
				flush()
				actions = append(actions, Action{Kind: ActionFocusUp})
			case 'B':
				flush()
				actions = append(actions, Action{Kind: ActionFocusDown})
			case 'C':
				flush()
				actions = append(actions, Action{Kind: ActionFocusRight})
			case 'D':
				flush()
				actions = append(actions, Action{Kind: ActionFocusLeft})
			default:
				buf = append(buf, f.Prefix, 0x1b, '[', b)
			}
			continue
		case prefixAwaitEscBracket:
			if b == '[' {
				f.state = prefixAwaitCSI
			} else {
				f.state = prefixIdle
				buf = append(buf, f.Prefix, 0x1b, b)
			}
			continue
		case prefixAwaitKey:
			if b == 0x1b {
				f.state = prefixAwaitEscBracket
				continue
			}
			f.state = prefixIdle
			switch {
			case b == 'd' || b == 'D':
				flush()
				actions = append(actions, Action{Kind: ActionDetach})
			case b == '%':
				flush()
				actions = append(actions, Action{Kind: ActionSplitH})
			case b == '"':
				flush()
				actions = append(actions, Action{Kind: ActionSplitV})
			case b == 'o':
				flush()
				actions = append(actions, Action{Kind: ActionNextPane})
			case b == 'x':
				flush()
				actions = append(actions, Action{Kind: ActionClosePane})
			case b == 'c':
				flush()
				actions = append(actions, Action{Kind: ActionNewWindow})
			case b == 'n':
				flush()
				actions = append(actions, Action{Kind: ActionNextWindow})
			case b == 'p':
				flush()
				actions = append(actions, Action{Kind: ActionPrevWindow})
			case b == '&':
				flush()
				actions = append(actions, Action{Kind: ActionCloseWindow})
			case b == 'm' || b == '?':
				flush()
				actions = append(actions, Action{Kind: ActionOpenMenu})
			case b == 'w':
				flush()
				actions = append(actions, Action{Kind: ActionOpenWindowSwitcher})
			case b >= '1' && b <= '9':
				flush()
				actions = append(actions, Action{Kind: ActionSelectWindow, Index: int(b - '0')})
			default:
				if b == f.Prefix {
					buf = append(buf, f.Prefix)
				} else {
					buf = append(buf, f.Prefix, b)
				}
			}
			continue
		}
		if b == f.Prefix {
			f.state = prefixAwaitKey
			continue
		}
		buf = append(buf, b)
	}
	flush()
	return actions
}

// FilterAutoReplies drops outer-terminal DA1/DA2/CPR responses so the host VT remains sole responder.
func FilterAutoReplies(data []byte) []byte {
	if len(data) < 3 {
		return data
	}
	var out []byte
	i := 0
	for i < len(data) {
		if data[i] == 0x1b && i+1 < len(data) && data[i+1] == '[' {
			if end := matchAutoReplyCSI(data[i:]); end > 0 {
				if out == nil {
					out = make([]byte, 0, len(data))
					out = append(out, data[:i]...)
				}
				i += end
				continue
			}
		}
		if out != nil {
			out = append(out, data[i])
		}
		i++
	}
	if out == nil {
		return data
	}
	return out
}

func matchAutoReplyCSI(s []byte) int {
	// Match ESC [ (?|>) digits/; c  (DA1/DA2) or ESC [ digits ; digits R (CPR).
	if len(s) < 4 || s[0] != 0x1b || s[1] != '[' {
		return 0
	}
	j := 2
	prefix := byte(0)
	if s[j] == '?' || s[j] == '>' {
		prefix = s[j]
		j++
	}
	start := j
	hasSemi := false
	for j < len(s) && ((s[j] >= '0' && s[j] <= '9') || s[j] == ';') {
		if s[j] == ';' {
			hasSemi = true
		}
		j++
	}
	if j >= len(s) || j == start {
		return 0
	}
	final := s[j]
	if final == 'c' && (prefix == '?' || prefix == '>') {
		return j + 1
	}
	if final == 'R' && prefix == 0 && hasSemi {
		return j + 1
	}
	return 0
}

type AttachOptions struct {
	SessionID     string
	WindowID      string
	PaneID        string
	ClientID      string
	Prefix        byte
	In            io.Reader
	Out           io.Writer
	RawTTY        bool
	ShowStatusBar *bool // nil = auto-enabled on interactive raw TTY with >= 6 rows
	Cols          uint16
	Rows          uint16
}

// Attach connects a local CLI terminal (or custom streams in tests) to a native session pane.
// Detaching with Ctrl+b d closes only the client subscription and restores the local terminal.
func Attach(ctx context.Context, backend sessionbackend.SessionBackend, layout sessionbackend.LayoutBackend, opts AttachOptions) error {
	if opts.SessionID == "" {
		return fmt.Errorf("nativeattach: session ID required")
	}
	if opts.In == nil {
		opts.In = os.Stdin
	}
	if opts.Out == nil {
		opts.Out = os.Stdout
	}
	if opts.ClientID == "" {
		opts.ClientID = fmt.Sprintf("cli-%d-%d", os.Getpid(), time.Now().UnixNano())
	}

	var inFD uintptr
	var hasFD bool
	if f, ok := opts.In.(*os.File); ok {
		inFD = f.Fd()
		hasFD = ttyraw.IsTerminal(inFD)
	}
	if opts.RawTTY && hasFD {
		restore, err := ttyraw.MakeRaw(inFD)
		if err != nil {
			return fmt.Errorf("nativeattach: enter raw mode: %w", err)
		}
		defer func() {
			_, _ = io.WriteString(opts.Out, terminalResetOnExit)
			restore()
		}()
	}

	cols, rows := opts.Cols, opts.Rows
	if (cols == 0 || rows == 0) && hasFD {
		if c, r, err := ttyraw.Size(inFD); err == nil && c > 0 && r > 0 {
			cols, rows = c, r
		}
	}
	if cols == 0 {
		cols = 80
	}
	if rows == 0 {
		rows = 24
	}

	showStatus := opts.RawTTY && hasFD && rows >= 6
	if opts.ShowStatusBar != nil {
		showStatus = *opts.ShowStatusBar && rows >= 6
	}
	paneRowsFor := func(termRows uint16) uint16 {
		if showStatus && termRows >= 6 {
			return termRows - 1
		}
		return termRows
	}

	state, err := backend.Observe(ctx, opts.SessionID)
	if err != nil {
		return err
	}
	if state.Status == sessionbackend.StatusExited {
		return fmt.Errorf("session %q already exited", opts.SessionID)
	}
	paneID := opts.PaneID
	if paneID == "" && opts.WindowID != "" {
		for _, w := range state.Windows {
			if w.ID == opts.WindowID {
				if layout != nil {
					_ = layout.SelectWindow(ctx, opts.SessionID, w.ID)
				}
				paneID = w.ActivePaneID
				if paneID == "" && w.Layout != nil {
					if ids := w.Layout.PaneIDs(); len(ids) > 0 {
						paneID = ids[0]
					}
				}
				break
			}
		}
	}
	if paneID == "" {
		paneID = state.ActivePaneID
	}

	attachCtx, cancelAttach := context.WithCancel(ctx)
	defer cancelAttach()

	// Single stdin reader goroutine lives for the entire attach session so pane/window switches
	// and interactive menus never leak a blocked os.Stdin.Read goroutine.
	inCh := make(chan []byte, 32)
	inErrCh := make(chan error, 1)
	go func() {
		buf := make([]byte, 4096)
		for {
			n, rerr := opts.In.Read(buf)
			if n > 0 {
				cp := make([]byte, n)
				copy(cp, buf[:n])
				select {
				case inCh <- cp:
				case <-attachCtx.Done():
					return
				}
			}
			if rerr != nil {
				select {
				case inErrCh <- rerr:
				default:
				}
				return
			}
		}
	}()

	var curCols atomic.Uint32
	var curRows atomic.Uint32
	curCols.Store(uint32(cols))
	curRows.Store(uint32(rows))

	var writeMu sync.Mutex
	writeOut := func(b []byte) error {
		writeMu.Lock()
		defer writeMu.Unlock()
		_, werr := opts.Out.Write(b)
		return werr
	}

	buildStatusSeq := func(pane string, prefixPending bool) []byte {
		if !showStatus {
			return nil
		}
		c := uint16(curCols.Load())
		r := uint16(curRows.Load())
		if r < 6 {
			return nil
		}
		obsCtx, obsCancel := context.WithTimeout(attachCtx, 2*time.Second)
		st, err := backend.Observe(obsCtx, opts.SessionID)
		obsCancel()
		if err != nil {
			return nil
		}
		label := st.Label
		if label == "" {
			label = st.SessionID
		}
		activeWin := st.ActiveWindowID
		for _, w := range st.Windows {
			if w.Layout != nil && w.Layout.ContainsPane(pane) {
				activeWin = w.ID
				break
			}
		}
		return renderStatusBarSequence(statusBarInfo{
			SessionLabel:   label,
			Windows:        st.Windows,
			ActiveWindowID: activeWin,
			ActivePaneID:   pane,
			PrefixPending:  prefixPending,
		}, c, r)
	}

	drawStatusBar := func(pane string, prefixPending bool) {
		if seq := buildStatusSeq(pane, prefixPending); len(seq) > 0 {
			_ = writeOut(seq)
		}
	}

	var resizeTargetMu sync.Mutex
	var activeTarget sessionbackend.Target
	var activeGen uint64
	var inComposite atomic.Bool
	resizeCh := make(chan struct{}, 1)
	if hasFD {
		go ttyraw.WatchResize(attachCtx, inFD, func(c, r uint16) {
			curCols.Store(uint32(c))
			curRows.Store(uint32(r))
			if inComposite.Load() {
				select {
				case resizeCh <- struct{}{}:
				default:
				}
				return
			}
			resizeTargetMu.Lock()
			t := activeTarget
			gen := activeGen
			resizeTargetMu.Unlock()
			if showStatus && r >= 6 {
				_ = writeOut([]byte(applyScrollRegion(paneRowsFor(r))))
			}
			if t.SessionID != "" && gen > 0 {
				_ = backend.Resize(attachCtx, t, gen, c, paneRowsFor(r))
			}
			drawStatusBar(t.PaneID, false)
		})
	}

	filter := NewPrefixFilter(opts.Prefix)

	for {
		// Check whether the window containing paneID currently has multiple tiled panes.
		var multiWin *sessionbackend.Window
		if curSt, oerr := backend.Observe(attachCtx, opts.SessionID); oerr == nil && curSt.Status == sessionbackend.StatusAlive {
			for i := range curSt.Windows {
				w := curSt.Windows[i]
				if w.Layout != nil && (w.Layout.ContainsPane(paneID) || (paneID == "" && w.ID == curSt.ActiveWindowID)) {
					if len(w.Layout.PaneIDs()) > 1 {
						cp := w.Clone()
						multiWin = &cp
					}
					break
				}
			}
		}

		var switchPane string
		var detached, exited bool
		var runErr error

		if multiWin != nil {
			inComposite.Store(true)
			switchPane, detached, exited, runErr = pumpMultiPane(
				attachCtx, backend, layout, opts.SessionID, *multiWin, paneID, opts.ClientID,
				inCh, inErrCh, resizeCh, &curCols, &curRows, paneRowsFor, filter, writeOut, buildStatusSeq,
			)
			inComposite.Store(false)
		} else {
			target := sessionbackend.Target{SessionID: opts.SessionID, PaneID: paneID}
			lease, err := backend.ClaimControl(attachCtx, target, opts.ClientID)
			if err != nil {
				return err
			}
			controlGen := lease.ControlGen
			paneID = lease.PaneID
			target.PaneID = paneID

			resizeTargetMu.Lock()
			activeTarget = target
			activeGen = controlGen
			resizeTargetMu.Unlock()

			c := uint16(curCols.Load())
			r := uint16(curRows.Load())
			pRows := paneRowsFor(r)
			if showStatus && r >= 6 {
				_ = writeOut([]byte(applyScrollRegion(pRows)))
			}
			_ = backend.Resize(attachCtx, target, controlGen, c, pRows)

			stream, err := backend.Attach(attachCtx, target, sessionbackend.AttachOpts{ClientID: opts.ClientID})
			if err != nil {
				_ = backend.ReleaseControl(context.Background(), target, opts.ClientID, controlGen)
				return err
			}

			switchPane, detached, exited, runErr = pumpPane(
				attachCtx, backend, layout, target, opts.ClientID, &controlGen, &resizeTargetMu, &activeGen,
				stream, inCh, inErrCh, filter, writeOut, drawStatusBar, showStatus, c, pRows,
			)
			_ = stream.Close()
			_ = backend.ReleaseControl(context.Background(), target, opts.ClientID, controlGen)
		}

		if runErr != nil {
			return runErr
		}
		if detached {
			if opts.RawTTY && hasFD {
				_, _ = io.WriteString(opts.Out, terminalResetOnExit)
			}
			_, _ = fmt.Fprintf(opts.Out, "\r\n[detached from %s]\r\n", opts.SessionID)
			return nil
		}
		if switchPane != "" {
			paneID = switchPane
			continue
		}
		if exited {
			if next, ok := pickNextPane(attachCtx, backend, opts.SessionID, paneID); ok && next != paneID {
				paneID = next
				continue
			}
			if opts.RawTTY && hasFD {
				_, _ = io.WriteString(opts.Out, terminalResetOnExit)
			}
			_, _ = fmt.Fprintf(opts.Out, "\r\n[session %s exited]\r\n", opts.SessionID)
			return nil
		}
		return nil
	}
}

func pumpPane(
	ctx context.Context,
	backend sessionbackend.SessionBackend,
	layout sessionbackend.LayoutBackend,
	target sessionbackend.Target,
	clientID string,
	controlGen *uint64,
	resizeMu *sync.Mutex,
	activeGen *uint64,
	stream sessionbackend.PaneStream,
	inCh <-chan []byte,
	inErrCh <-chan error,
	filter *PrefixFilter,
	writeOut func([]byte) error,
	drawStatusBar func(pane string, prefixPending bool),
	showStatus bool,
	cols, paneRows uint16,
) (switchPane string, detached bool, exited bool, err error) {
	writeInput := func(data []byte) error {
		if len(data) == 0 {
			return nil
		}
		werr := backend.WriteInput(ctx, target, *controlGen, data)
		if errors.Is(werr, sessionbackend.ErrStaleControl) {
			lease, cerr := backend.ClaimControl(ctx, target, clientID)
			if cerr != nil {
				return cerr
			}
			*controlGen = lease.ControlGen
			resizeMu.Lock()
			*activeGen = lease.ControlGen
			resizeMu.Unlock()
			werr = backend.WriteInput(ctx, target, *controlGen, data)
		}
		return werr
	}

	for {
		select {
		case <-ctx.Done():
			return "", true, false, nil

		case ev, ok := <-stream.Events():
			if !ok {
				return "", false, true, nil
			}
			switch ev.Kind {
			case sessionbackend.EventSnapshot:
				if showStatus {
					if err := writeOut([]byte(applyScrollRegion(paneRows) + clearScreenHome)); err != nil {
						return "", false, false, err
					}
				} else {
					if err := writeOut([]byte(clearScreenHome)); err != nil {
						return "", false, false, err
					}
				}
				if len(ev.Data) > 0 {
					if err := writeOut(ev.Data); err != nil {
						return "", false, false, err
					}
				}
				drawStatusBar(target.PaneID, filter.Pending())
			case sessionbackend.EventOutput:
				if len(ev.Data) > 0 {
					if err := writeOut(ev.Data); err != nil {
						return "", false, false, err
					}
					if showStatus && outputMayResetStatusBar(ev.Data) {
						_ = writeOut([]byte(applyScrollRegion(paneRows)))
						drawStatusBar(target.PaneID, filter.Pending())
					}
				}
			case sessionbackend.EventLayoutChanged:
				if ev.Window != nil && ev.Window.Layout != nil && len(ev.Window.Layout.PaneIDs()) > 1 {
					return target.PaneID, false, false, nil
				}
				drawStatusBar(target.PaneID, filter.Pending())
			case sessionbackend.EventResyncNeeded:
				return target.PaneID, false, false, nil
			case sessionbackend.EventExited:
				return "", false, true, nil
			}

		case chunk := <-inCh:
			cleaned := FilterAutoReplies(chunk)
			if len(cleaned) == 0 {
				continue
			}
			wasPending := filter.Pending()
			actions := filter.Feed(cleaned)
			nowPending := filter.Pending()
			if nowPending != wasPending {
				drawStatusBar(target.PaneID, nowPending)
			}
			for _, act := range actions {
				switch act.Kind {
				case ActionForward:
					if err := writeInput(act.Data); err != nil {
						return "", false, false, err
					}
				case ActionDetach:
					return "", true, false, nil
				case ActionSplitH, ActionSplitV:
					dir := sessionbackend.SplitHorizontal
					if act.Kind == ActionSplitV {
						dir = sessionbackend.SplitVertical
					}
					if newPaneID, ok := splitCurrentPane(ctx, layout, target.SessionID, target.PaneID, dir, cols, paneRows); ok {
						return newPaneID, false, false, nil
					}
				case ActionNextPane:
					if next, ok := pickNextPaneInWindow(ctx, backend, layout, target.SessionID, target.PaneID); ok && next != target.PaneID {
						return next, false, false, nil
					}
				case ActionClosePane:
					res := closeCurrentPane(ctx, backend, layout, target.SessionID, target.PaneID)
					if res.exited {
						return "", false, true, nil
					}
					if res.switchPane != "" {
						return res.switchPane, false, false, nil
					}
				case ActionNewWindow:
					if pane, ok := createAndSelectWindow(ctx, layout, target.SessionID, cols, paneRows); ok {
						return pane, false, false, nil
					}
				case ActionNextWindow:
					if pane, ok := stepWindow(ctx, backend, layout, target.SessionID, target.PaneID, +1); ok {
						return pane, false, false, nil
					}
				case ActionPrevWindow:
					if pane, ok := stepWindow(ctx, backend, layout, target.SessionID, target.PaneID, -1); ok {
						return pane, false, false, nil
					}
				case ActionSelectWindow:
					if pane, ok := selectWindowByNumber(ctx, backend, layout, target.SessionID, act.Index); ok {
						return pane, false, false, nil
					}
				case ActionCloseWindow:
					res := closeCurrentWindow(ctx, backend, layout, target.SessionID, target.PaneID)
					if res.exited {
						return "", false, true, nil
					}
					if res.switchPane != "" {
						return res.switchPane, false, false, nil
					}
				case ActionOpenMenu:
					res, oerr := runCommandMenu(ctx, backend, layout, target.SessionID, target.PaneID, inCh, inErrCh, writeOut, cols, paneRows)
					if oerr != nil {
						return "", false, false, oerr
					}
					if res.detached {
						return "", true, false, nil
					}
					if res.exited {
						return "", false, true, nil
					}
					if res.switchPane != "" {
						return res.switchPane, false, false, nil
					}
					return target.PaneID, false, false, nil
				case ActionOpenWindowSwitcher:
					res, oerr := runWindowSwitcher(ctx, backend, layout, target.SessionID, target.PaneID, inCh, inErrCh, writeOut, cols, paneRows)
					if oerr != nil {
						return "", false, false, oerr
					}
					if res.detached {
						return "", true, false, nil
					}
					if res.exited {
						return "", false, true, nil
					}
					if res.switchPane != "" {
						return res.switchPane, false, false, nil
					}
					return target.PaneID, false, false, nil
				}
			}

		case rerr := <-inErrCh:
			if errors.Is(rerr, io.EOF) {
				return "", true, false, nil
			}
			return "", false, false, rerr
		}
	}
}

func pickNextPane(ctx context.Context, backend sessionbackend.SessionBackend, sessionID, currentPaneID string) (string, bool) {
	st, err := backend.Observe(ctx, sessionID)
	if err != nil || st.Status != sessionbackend.StatusAlive {
		return "", false
	}
	var panes []string
	for _, w := range st.Windows {
		if w.Layout == nil {
			continue
		}
		panes = append(panes, w.Layout.PaneIDs()...)
	}
	if len(panes) == 0 {
		if st.ActivePaneID != "" {
			return st.ActivePaneID, true
		}
		return "", false
	}
	for i, id := range panes {
		if id == currentPaneID {
			return panes[(i+1)%len(panes)], true
		}
	}
	return panes[0], true
}
