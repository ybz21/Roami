package sessionhost

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/terminal"
)

const (
	defaultReplayBytes = 2 << 20  // 2 MiB bounded output history per pane
	defaultMaxLogBytes = 10 << 20 // 10 MiB per log file before single-generation rotation
	subChannelSize     = 128
)

type outputChunk struct {
	seq  uint64
	data []byte
}

type paneSub struct {
	id       string
	readOnly bool
	ch       chan sessionbackend.StreamEvent
	closed   bool
	desynced bool
	once     sync.Once
	onClose  func()
}

func (s *paneSub) Events() <-chan sessionbackend.StreamEvent { return s.ch }

func (s *paneSub) Close() error {
	s.once.Do(func() {
		if s.onClose != nil {
			s.onClose()
		}
	})
	return nil
}

// managedPane owns one running terminal.Terminal, its VT emulator, replay ring, log writer, and subscribers.
type managedPane struct {
	id         string
	sessionID  string
	paneGen    int64
	term       terminal.Terminal
	processID  string
	initialDir string
	createdAt  time.Time

	mu           sync.Mutex
	vt           *Emulator
	seq          uint64
	replay       []outputChunk
	replayBytes  int
	maxReplay    int
	subs         map[*paneSub]struct{}
	controller   string
	controlGen   uint64
	lastInputAt  time.Time
	lastOutputAt time.Time

	exited        bool
	outputDrained bool
	exitResult    terminal.ExitResult
	doneCh        chan struct{}

	// Serializes writes/submits so managed paste+Enter is never interleaved with interactive input.
	inputMu  sync.Mutex
	receipts map[string]sessionbackend.SubmitReceipt

	logPath string
	logFile *os.File
	logSize int64
}

func newManagedPane(sessionID, paneID string, paneGen int64, term terminal.Terminal, processID, initialDir, logPath string, cols, rows uint16) *managedPane {
	now := time.Now()
	p := &managedPane{
		id:           paneID,
		sessionID:    sessionID,
		paneGen:      paneGen,
		term:         term,
		processID:    processID,
		initialDir:   initialDir,
		createdAt:    now,
		vt:           NewEmulator(cols, rows, DefaultScrollback),
		maxReplay:    defaultReplayBytes,
		subs:         make(map[*paneSub]struct{}),
		lastInputAt:  now,
		lastOutputAt: now,
		doneCh:       make(chan struct{}),
		receipts:     make(map[string]sessionbackend.SubmitReceipt),
		logPath:      logPath,
	}
	if logPath != "" {
		if err := os.MkdirAll(filepath.Dir(logPath), 0700); err == nil {
			if f, err := os.OpenFile(logPath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0600); err == nil {
				if st, err := f.Stat(); err == nil {
					p.logSize = st.Size()
				}
				p.logFile = f
			}
		}
	}
	go p.readLoop()
	go p.waitLoop()
	return p
}

func (p *managedPane) readLoop() {
	buf := make([]byte, 16384)
	for {
		n, err := p.term.Read(buf)
		if n > 0 {
			chunk := make([]byte, n)
			copy(chunk, buf[:n])
			p.handleOutput(chunk)
		}
		if err != nil {
			if err != io.EOF {
				// Record EOF/drain cleanly even on EIO/broken pipe.
			}
			p.handleDrained()
			return
		}
	}
}

func (p *managedPane) waitLoop() {
	res, _ := p.term.Wait()
	p.mu.Lock()
	p.exited = true
	p.exitResult = res
	exitCode := res.ExitCode
	p.seq++
	ev := sessionbackend.StreamEvent{
		Seq:      p.seq,
		PaneID:   p.id,
		PaneGen:  p.paneGen,
		Kind:     sessionbackend.EventExited,
		ExitCode: &exitCode,
		Signal:   res.Signal,
		Drained:  p.outputDrained,
	}
	p.broadcastLocked(ev)
	drained := p.outputDrained
	p.mu.Unlock()
	if drained {
		p.finishClose()
	}
}

func (p *managedPane) handleDrained() {
	p.mu.Lock()
	p.outputDrained = true
	exited := p.exited
	if exited {
		exitCode := p.exitResult.ExitCode
		p.seq++
		p.broadcastLocked(sessionbackend.StreamEvent{
			Seq:      p.seq,
			PaneID:   p.id,
			PaneGen:  p.paneGen,
			Kind:     sessionbackend.EventExited,
			ExitCode: &exitCode,
			Signal:   p.exitResult.Signal,
			Drained:  true,
		})
	}
	p.mu.Unlock()
	if exited {
		p.finishClose()
	}
}

func (p *managedPane) finishClose() {
	p.mu.Lock()
	if p.logFile != nil {
		_ = p.logFile.Close()
		p.logFile = nil
	}
	select {
	case <-p.doneCh:
	default:
		close(p.doneCh)
	}
	p.mu.Unlock()
}

func (p *managedPane) handleOutput(chunk []byte) {
	p.mu.Lock()
	replies, modeChanged := p.vt.Feed(chunk)
	p.lastOutputAt = time.Now()
	p.seq++
	seq := p.seq
	p.appendReplayLocked(seq, chunk)
	p.writeLogLocked(chunk)
	p.broadcastLocked(sessionbackend.StreamEvent{
		Seq:     seq,
		PaneID:  p.id,
		PaneGen: p.paneGen,
		Kind:    sessionbackend.EventOutput,
		Data:    chunk,
	})
	if modeChanged {
		mode := p.vt.Mode()
		p.seq++
		p.broadcastLocked(sessionbackend.StreamEvent{
			Seq:     p.seq,
			PaneID:  p.id,
			PaneGen: p.paneGen,
			Kind:    sessionbackend.EventMode,
			Mode:    &mode,
		})
	}
	p.mu.Unlock()

	// Answer DA/DSR queries directly from the server-side VT (required for ConPTY ESC[6n).
	for _, reply := range replies {
		p.inputMu.Lock()
		_, _ = p.term.Write(reply)
		p.inputMu.Unlock()
	}
}

func (p *managedPane) appendReplayLocked(seq uint64, data []byte) {
	p.replay = append(p.replay, outputChunk{seq: seq, data: data})
	p.replayBytes += len(data)
	for p.replayBytes > p.maxReplay && len(p.replay) > 1 {
		p.replayBytes -= len(p.replay[0].data)
		p.replay = p.replay[1:]
	}
}

func (p *managedPane) writeLogLocked(data []byte) {
	if p.logFile == nil {
		return
	}
	if p.logSize+int64(len(data)) > defaultMaxLogBytes {
		_ = p.logFile.Close()
		_ = os.Rename(p.logPath, p.logPath+".1")
		f, err := os.OpenFile(p.logPath, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0600)
		if err != nil {
			p.logFile = nil
			return
		}
		p.logFile = f
		p.logSize = 0
	}
	n, _ := p.logFile.Write(data)
	p.logSize += int64(n)
}

func (p *managedPane) broadcastLocked(ev sessionbackend.StreamEvent) {
	for sub := range p.subs {
		if sub.closed || sub.desynced {
			continue
		}
		select {
		case sub.ch <- ev:
		default:
			// Slow subscriber: never stall PTY or other subscribers; ask this client to resync.
			sub.desynced = true
			resync := sessionbackend.StreamEvent{
				Seq:     p.seq,
				PaneID:  p.id,
				PaneGen: p.paneGen,
				Kind:    sessionbackend.EventResyncNeeded,
			}
			select {
			case sub.ch <- resync:
			default:
			}
		}
	}
}

func (p *managedPane) broadcastLayout(win sessionbackend.Window) {
	cp := win.Clone()
	p.mu.Lock()
	p.seq++
	p.broadcastLocked(sessionbackend.StreamEvent{
		Seq:     p.seq,
		PaneID:  p.id,
		PaneGen: p.paneGen,
		Kind:    sessionbackend.EventLayoutChanged,
		Window:  &cp,
	})
	p.mu.Unlock()
}

func (p *managedPane) attach(opts sessionbackend.AttachOpts) sessionbackend.PaneStream {
	p.mu.Lock()
	defer p.mu.Unlock()

	sub := &paneSub{
		id:       opts.ClientID,
		readOnly: opts.ReadOnly,
		ch:       make(chan sessionbackend.StreamEvent, subChannelSize),
	}
	sub.onClose = func() {
		p.detach(sub)
	}

	// Decide incremental replay vs full snapshot at an exact sequence boundary.
	replayed := false
	if opts.LastSeq > 0 && opts.LastSeq <= p.seq && len(p.replay) > 0 {
		firstSeq := p.replay[0].seq
		if opts.LastSeq+1 >= firstSeq {
			for _, c := range p.replay {
				if c.seq > opts.LastSeq {
					sub.ch <- sessionbackend.StreamEvent{
						Seq:     c.seq,
						PaneID:  p.id,
						PaneGen: p.paneGen,
						Kind:    sessionbackend.EventOutput,
						Data:    c.data,
					}
				}
			}
			mode := p.vt.Mode()
			sub.ch <- sessionbackend.StreamEvent{
				Seq:     p.seq,
				PaneID:  p.id,
				PaneGen: p.paneGen,
				Kind:    sessionbackend.EventMode,
				Mode:    &mode,
			}
			replayed = true
		}
	}

	if !replayed {
		mode := p.vt.Mode()
		sub.ch <- sessionbackend.StreamEvent{
			Seq:        p.seq,
			PaneID:     p.id,
			PaneGen:    p.paneGen,
			Kind:       sessionbackend.EventSnapshot,
			Data:       p.vt.SnapshotANSI(),
			Mode:       &mode,
			ControlGen: p.controlGen,
			Controller: p.controller,
		}
	}
	if p.exited {
		code := p.exitResult.ExitCode
		sub.ch <- sessionbackend.StreamEvent{
			Seq:      p.seq,
			PaneID:   p.id,
			PaneGen:  p.paneGen,
			Kind:     sessionbackend.EventExited,
			ExitCode: &code,
			Signal:   p.exitResult.Signal,
			Drained:  p.outputDrained,
		}
	}
	p.subs[sub] = struct{}{}
	return sub
}

func (p *managedPane) detach(sub *paneSub) {
	p.mu.Lock()
	if !sub.closed {
		sub.closed = true
		delete(p.subs, sub)
		close(sub.ch)
	}
	// Release control automatically when the controlling client disconnects, keeping current size.
	if sub.id != "" && p.controller == sub.id {
		p.controller = ""
		p.seq++
		p.broadcastLocked(sessionbackend.StreamEvent{
			Seq:        p.seq,
			PaneID:     p.id,
			PaneGen:    p.paneGen,
			Kind:       sessionbackend.EventControl,
			ControlGen: p.controlGen,
			Controller: "",
		})
	}
	p.mu.Unlock()
}

func (p *managedPane) claimControl(clientID string) sessionbackend.ControlLease {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.controlGen++
	p.controller = clientID
	p.seq++
	p.broadcastLocked(sessionbackend.StreamEvent{
		Seq:        p.seq,
		PaneID:     p.id,
		PaneGen:    p.paneGen,
		Kind:       sessionbackend.EventControl,
		ControlGen: p.controlGen,
		Controller: p.controller,
	})
	return sessionbackend.ControlLease{
		PaneID:     p.id,
		Controller: p.controller,
		ControlGen: p.controlGen,
	}
}

func (p *managedPane) releaseControl(clientID string, controlGen uint64) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	if controlGen != 0 && controlGen != p.controlGen {
		return sessionbackend.ErrStaleControl
	}
	if clientID != "" && p.controller != "" && p.controller != clientID {
		return sessionbackend.ErrStaleControl
	}
	p.controller = ""
	p.seq++
	p.broadcastLocked(sessionbackend.StreamEvent{
		Seq:        p.seq,
		PaneID:     p.id,
		PaneGen:    p.paneGen,
		Kind:       sessionbackend.EventControl,
		ControlGen: p.controlGen,
		Controller: "",
	})
	return nil
}

func (p *managedPane) checkControlLocked(controlGen uint64) error {
	if controlGen > 0 && controlGen != p.controlGen {
		return sessionbackend.ErrStaleControl
	}
	if p.controller != "" && controlGen == 0 {
		return sessionbackend.ErrStaleControl
	}
	return nil
}

func (p *managedPane) writeInput(controlGen uint64, data []byte) error {
	p.mu.Lock()
	if err := p.checkControlLocked(controlGen); err != nil {
		p.mu.Unlock()
		return err
	}
	p.lastInputAt = time.Now()
	p.mu.Unlock()

	p.inputMu.Lock()
	defer p.inputMu.Unlock()
	_, err := p.term.Write(data)
	return err
}

func (p *managedPane) submit(req sessionbackend.SubmitReq) (sessionbackend.SubmitReceipt, error) {
	p.inputMu.Lock()
	defer p.inputMu.Unlock()

	if req.RequestID != "" {
		if prev, ok := p.receipts[req.RequestID]; ok {
			prev.Duplicate = true
			return prev, nil
		}
	}

	p.mu.Lock()
	mode := p.vt.Mode()
	p.lastInputAt = time.Now()
	p.mu.Unlock()

	payload := []byte(req.Payload)
	if req.BracketedPaste && mode.BracketedPaste {
		wrapped := make([]byte, 0, len(payload)+12)
		wrapped = append(wrapped, "\x1b[200~"...)
		wrapped = append(wrapped, payload...)
		wrapped = append(wrapped, "\x1b[201~"...)
		payload = wrapped
	}
	if len(payload) > 0 {
		if _, err := p.term.Write(payload); err != nil {
			return sessionbackend.SubmitReceipt{}, err
		}
	}
	if req.SubmitEnter {
		// Brief settle so bracketed-paste TUI apps commit the pasted text before Enter submits.
		time.Sleep(15 * time.Millisecond)
		if _, err := p.term.Write([]byte{'\r'}); err != nil {
			return sessionbackend.SubmitReceipt{}, err
		}
	}

	receipt := sessionbackend.SubmitReceipt{
		RequestID: req.RequestID,
		Accepted:  true,
		At:        time.Now(),
	}
	if req.RequestID != "" {
		p.receipts[req.RequestID] = receipt
	}
	return receipt, nil
}

func (p *managedPane) resize(controlGen uint64, cols, rows uint16) error {
	if cols < terminal.MinCols || rows < terminal.MinRows || cols > 1000 || rows > 500 {
		return nil // Guard against tiny/collapsed layouts, matching backend/pty.
	}
	p.mu.Lock()
	if err := p.checkControlLocked(controlGen); err != nil {
		p.mu.Unlock()
		return err
	}
	cur := p.vt.Mode()
	if cur.Cols == cols && cur.Rows == rows {
		p.mu.Unlock()
		return nil
	}
	if err := p.term.Resize(cols, rows); err != nil {
		p.mu.Unlock()
		return err
	}
	p.vt.Resize(cols, rows)
	next := p.vt.Mode()
	p.seq++
	p.broadcastLocked(sessionbackend.StreamEvent{
		Seq:     p.seq,
		PaneID:  p.id,
		PaneGen: p.paneGen,
		Kind:    sessionbackend.EventResized,
		Mode:    &next,
	})
	p.mu.Unlock()
	return nil
}

// moveCursor translates a clicked cell into horizontal arrow keys using the server VT's cursor,
// DECCKM mode, and dim/gray lastRealCol guard (preventing accidental prompt-suggestion acceptance).
func (p *managedPane) moveCursor(controlGen uint64, col, row int) error {
	if col < 0 || row < 0 {
		return nil
	}
	p.mu.Lock()
	if err := p.checkControlLocked(controlGen); err != nil {
		p.mu.Unlock()
		return err
	}
	mode := p.vt.Mode()
	dx, dy := col-mode.CursorX, row-mode.CursorY
	steps := 0
	if mode.AltScreen {
		if dy == 0 {
			if dx > 0 {
				last := p.vt.LastRealCol(mode.CursorY)
				if mode.CursorX+dx > last+1 {
					dx = last + 1 - mode.CursorX
				}
				if dx > 0 {
					steps = dx
				}
			} else {
				steps = dx
			}
		}
	} else if dy >= -3 && dy <= 3 {
		steps = dy*int(mode.Cols) + dx
	}
	decckm := mode.DECCKM
	if steps != 0 {
		p.lastInputAt = time.Now()
	}
	p.mu.Unlock()

	if steps == 0 {
		return nil
	}
	var seq string
	if steps > 0 {
		if decckm {
			seq = "\x1bOC"
		} else {
			seq = "\x1b[C"
		}
		seq = strings.Repeat(seq, steps)
	} else {
		if decckm {
			seq = "\x1bOD"
		} else {
			seq = "\x1b[D"
		}
		seq = strings.Repeat(seq, -steps)
	}
	p.inputMu.Lock()
	defer p.inputMu.Unlock()
	_, err := p.term.Write([]byte(seq))
	return err
}

func (p *managedPane) capture(opts sessionbackend.CaptureOpts) sessionbackend.CaptureResult {
	p.mu.Lock()
	defer p.mu.Unlock()
	lines := opts.Lines
	if lines <= 0 {
		lines = 200
	}
	return sessionbackend.CaptureResult{
		Text:    p.vt.CaptureText(lines, opts.IncludeHistory),
		PaneGen: p.paneGen,
		Mode:    p.vt.Mode(),
	}
}

func (p *managedPane) cwd() string {
	p.mu.Lock()
	c := p.vt.Cwd()
	p.mu.Unlock()
	if c != "" {
		return c
	}
	return p.initialDir
}

func (p *managedPane) terminate(ctx context.Context) error {
	err := p.term.Terminate(ctx, 2*time.Second)
	_ = p.term.Close()
	p.finishClose()
	return err
}

func (p *managedPane) status() (alive bool, exit terminal.ExitResult, attached int, lastAct time.Time) {
	p.mu.Lock()
	defer p.mu.Unlock()
	act := p.lastOutputAt
	if p.lastInputAt.After(act) {
		act = p.lastInputAt
	}
	return !p.exited, p.exitResult, len(p.subs), act
}

func (p *managedPane) logSummary() string {
	return fmt.Sprintf("pane=%s pid=%d seq=%d", p.id, p.term.PID(), p.seq)
}
