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
	terminalResetOnExit = "\x1b[?25h\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[0m"
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
)

type Action struct {
	Kind ActionKind
	Data []byte
}

// PrefixFilter intercepts tmux-style prefix key chords (Ctrl+b followed by d/%/"/o/x)
// while passing all other input untouched across arbitrary read chunk boundaries.
type PrefixFilter struct {
	Prefix  byte
	pending bool
}

func NewPrefixFilter(prefix byte) *PrefixFilter {
	if prefix == 0 {
		prefix = DefaultPrefix
	}
	return &PrefixFilter{Prefix: prefix}
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
		if f.pending {
			f.pending = false
			switch b {
			case 'd', 'D':
				flush()
				actions = append(actions, Action{Kind: ActionDetach})
			case '%':
				flush()
				actions = append(actions, Action{Kind: ActionSplitH})
			case '"':
				flush()
				actions = append(actions, Action{Kind: ActionSplitV})
			case 'o':
				flush()
				actions = append(actions, Action{Kind: ActionNextPane})
			case 'x':
				flush()
				actions = append(actions, Action{Kind: ActionClosePane})
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
			f.pending = true
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
	SessionID string
	PaneID    string
	ClientID  string
	Prefix    byte
	In        io.Reader
	Out       io.Writer
	RawTTY    bool
	Cols      uint16
	Rows      uint16
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

	state, err := backend.Observe(ctx, opts.SessionID)
	if err != nil {
		return err
	}
	if state.Status == sessionbackend.StatusExited {
		return fmt.Errorf("session %q already exited", opts.SessionID)
	}
	paneID := opts.PaneID
	if paneID == "" {
		paneID = state.ActivePaneID
	}

	attachCtx, cancelAttach := context.WithCancel(ctx)
	defer cancelAttach()

	// Single stdin reader goroutine lives for the entire attach session so pane switches
	// never leak a blocked os.Stdin.Read goroutine.
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

	var resizeTargetMu sync.Mutex
	var activeTarget sessionbackend.Target
	var activeGen uint64
	if hasFD {
		go ttyraw.WatchResize(attachCtx, inFD, func(c, r uint16) {
			curCols.Store(uint32(c))
			curRows.Store(uint32(r))
			resizeTargetMu.Lock()
			t := activeTarget
			gen := activeGen
			resizeTargetMu.Unlock()
			if t.SessionID != "" && gen > 0 {
				_ = backend.Resize(attachCtx, t, gen, c, r)
			}
		})
	}

	filter := NewPrefixFilter(opts.Prefix)

	for {
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

		_ = backend.Resize(attachCtx, target, controlGen, uint16(curCols.Load()), uint16(curRows.Load()))

		stream, err := backend.Attach(attachCtx, target, sessionbackend.AttachOpts{ClientID: opts.ClientID})
		if err != nil {
			_ = backend.ReleaseControl(context.Background(), target, opts.ClientID, controlGen)
			return err
		}

		switchPane, detached, exited, runErr := pumpPane(
			attachCtx, backend, layout, target, opts.ClientID, &controlGen, &resizeTargetMu, &activeGen,
			stream, inCh, inErrCh, filter, writeOut, uint16(curCols.Load()), uint16(curRows.Load()),
		)
		_ = stream.Close()
		_ = backend.ReleaseControl(context.Background(), target, opts.ClientID, controlGen)

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
			// If sibling panes remain in the session, move to the active remaining pane.
			if next, ok := pickNextPane(attachCtx, backend, opts.SessionID, paneID); ok && next != paneID {
				paneID = next
				continue
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
	cols, rows uint16,
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
				if err := writeOut([]byte(clearScreenHome)); err != nil {
					return "", false, false, err
				}
				if len(ev.Data) > 0 {
					if err := writeOut(ev.Data); err != nil {
						return "", false, false, err
					}
				}
			case sessionbackend.EventOutput:
				if len(ev.Data) > 0 {
					if err := writeOut(ev.Data); err != nil {
						return "", false, false, err
					}
				}
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
			for _, act := range filter.Feed(cleaned) {
				switch act.Kind {
				case ActionForward:
					if err := writeInput(act.Data); err != nil {
						return "", false, false, err
					}
				case ActionDetach:
					return "", true, false, nil
				case ActionSplitH, ActionSplitV:
					if layout == nil {
						continue
					}
					dir := sessionbackend.SplitHorizontal
					if act.Kind == ActionSplitV {
						dir = sessionbackend.SplitVertical
					}
					_, newPaneID, serr := layout.SplitPane(ctx, target.SessionID, target.PaneID, sessionbackend.SplitSpec{
						Dir:  dir,
						Cols: cols,
						Rows: rows,
					})
					if serr == nil && newPaneID != "" {
						return newPaneID, false, false, nil
					}
				case ActionNextPane:
					if next, ok := pickNextPane(ctx, backend, target.SessionID, target.PaneID); ok && next != target.PaneID {
						return next, false, false, nil
					}
				case ActionClosePane:
					if layout == nil {
						continue
					}
					win, cerr := layout.ClosePane(ctx, target.SessionID, target.PaneID)
					if cerr != nil {
						continue
					}
					if win == nil || win.ActivePaneID == "" {
						return "", false, true, nil
					}
					return win.ActivePaneID, false, false, nil
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
