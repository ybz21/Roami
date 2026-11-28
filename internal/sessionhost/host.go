package sessionhost

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/terminal"
)

type Config struct {
	HostID  string
	LogsDir string
	Coord   *CoordDB
	Backend terminal.TerminalBackend
}

type managedSession struct {
	id             string
	label          string
	dir            string
	createdAt      time.Time
	activeWindowID string
	windows        []sessionbackend.Window
	panes          map[string]*managedPane
}

// Host owns native terminal sessions, windows, split trees, and panes in-process.
// It implements both SessionBackend and LayoutBackend.
type Host struct {
	hostID  string
	logsDir string
	coord   *CoordDB
	backend terminal.TerminalBackend

	mu       sync.RWMutex
	sessions map[string]*managedSession
	seq      atomic.Uint64
	draining atomic.Bool
}

var (
	_ sessionbackend.SessionBackend = (*Host)(nil)
	_ sessionbackend.LayoutBackend  = (*Host)(nil)
)

func NewHost(cfg Config) *Host {
	b := cfg.Backend
	if b == nil {
		b = terminal.NewBackend()
	}
	id := cfg.HostID
	if id == "" {
		id = fmt.Sprintf("host-%d", time.Now().UnixNano())
	}
	return &Host{
		hostID:   id,
		logsDir:  cfg.LogsDir,
		coord:    cfg.Coord,
		backend:  b,
		sessions: make(map[string]*managedSession),
	}
}

func (h *Host) HostID() string                   { return h.hostID }
func (h *Host) Kind() sessionbackend.BackendKind { return sessionbackend.BackendNative }
func (h *Host) SetDraining(v bool)               { h.draining.Store(v) }
func (h *Host) IsDraining() bool                 { return h.draining.Load() }

func (h *Host) Capabilities() sessionbackend.CapabilitySet {
	caps := h.backend.Capabilities()
	return sessionbackend.CapabilitySet{
		Windows:        true,
		Splits:         true,
		MoveCursor:     true,
		ManagedSubmit:  true,
		MemoryLimit:    caps.MemoryLimit,
		Pause:          caps.Pause,
		ProcessInspect: caps.ProcessInspect,
	}
}

func (h *Host) nextID(prefix string) string {
	return fmt.Sprintf("%s-%d", prefix, h.seq.Add(1))
}

func (h *Host) ActivePaneCount() int {
	h.mu.RLock()
	defer h.mu.RUnlock()
	total := 0
	for _, s := range h.sessions {
		for _, p := range s.panes {
			if alive, _, _, _ := p.status(); alive {
				total++
			}
		}
	}
	return total
}

func specDigest(spec sessionbackend.CreateSpec) string {
	b, _ := json.Marshal(struct {
		SessionID string
		Label     string
		Dir       string
		Exe       string
		Args      []string
	}{spec.SessionID, spec.Label, spec.Dir, spec.Exe, spec.Args})
	return fmt.Sprintf("%x", sha256.Sum256(b))
}

func (h *Host) Create(ctx context.Context, spec sessionbackend.CreateSpec) (sessionbackend.SessionRef, error) {
	if h.coord != nil && spec.OperationID != "" {
		digest := specDigest(spec)
		op, existed, err := h.coord.AdmitCreate(spec.OperationID, digest, h.hostID, spec.ExpectedGeneration)
		if err != nil {
			return sessionbackend.SessionRef{}, err
		}
		if existed {
			if op.HostID != h.hostID {
				return sessionbackend.SessionRef{
					SessionID:      op.SessionID,
					Backend:        sessionbackend.BackendNative,
					HostInstanceID: op.HostID,
					Reused:         true,
				}, nil
			}
			if op.State == OpStateSucceeded && op.SessionID != "" {
				return h.sessionRef(op.SessionID, true)
			}
			return sessionbackend.SessionRef{}, fmt.Errorf("operation %s in state %s", op.OperationID, op.State)
		}
		claimed, err := h.coord.ClaimStart(spec.OperationID, h.hostID)
		if err != nil {
			return sessionbackend.SessionRef{}, err
		}
		if !claimed {
			return sessionbackend.SessionRef{}, fmt.Errorf("operation %s already claimed", spec.OperationID)
		}
	} else if h.draining.Load() {
		return sessionbackend.SessionRef{}, sessionbackend.ErrStaleGeneration
	}

	sessionID := spec.SessionID
	if sessionID == "" {
		sessionID = fmt.Sprintf("%s-%04x", time.Now().Format("2006-0102-1504"), h.seq.Add(1)&0xffff)
	}
	cols, rows := spec.Cols, spec.Rows
	if cols == 0 {
		cols = terminal.DefaultCols
	}
	if rows == 0 {
		rows = terminal.DefaultRows
	}

	winID := h.nextID("w")
	nodeID := h.nextID("n")
	paneID := h.nextID("p")
	pane, err := h.spawnPane(ctx, sessionID, paneID, terminal.LaunchSpec{
		Exe:        spec.Exe,
		Args:       spec.Args,
		Cwd:        spec.Dir,
		Env:        spec.Env,
		Cols:       cols,
		Rows:       rows,
		LoginShell: spec.LoginShell,
	})
	if err != nil {
		if h.coord != nil && spec.OperationID != "" {
			_ = h.coord.CompleteOperation(spec.OperationID, "", err.Error())
		}
		return sessionbackend.SessionRef{}, err
	}

	win := sessionbackend.NewSinglePaneWindow(winID, "main", nodeID, paneID)
	label := spec.Label
	if label == "" {
		label = sessionID
	}
	sess := &managedSession{
		id:             sessionID,
		label:          label,
		dir:            spec.Dir,
		createdAt:      time.Now(),
		activeWindowID: winID,
		windows:        []sessionbackend.Window{win},
		panes:          map[string]*managedPane{paneID: pane},
	}

	h.mu.Lock()
	if _, exists := h.sessions[sessionID]; exists {
		h.mu.Unlock()
		_ = pane.terminate(context.Background())
		if h.coord != nil && spec.OperationID != "" {
			_ = h.coord.CompleteOperation(spec.OperationID, "", "SESSION_EXISTS")
		}
		return sessionbackend.SessionRef{}, fmt.Errorf("session %s already exists", sessionID)
	}
	h.sessions[sessionID] = sess
	h.mu.Unlock()

	if h.coord != nil && spec.OperationID != "" {
		_ = h.coord.CompleteOperation(spec.OperationID, sessionID, "")
	}

	return sessionbackend.SessionRef{
		SessionID:      sessionID,
		Label:          label,
		Backend:        sessionbackend.BackendNative,
		HostInstanceID: h.hostID,
		WindowID:       winID,
		PaneID:         paneID,
		RunGeneration:  pane.paneGen,
		PID:            pane.term.PID(),
		ProcessID:      pane.processID,
	}, nil
}

func (h *Host) sessionRef(sessionID string, reused bool) (sessionbackend.SessionRef, error) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	s, ok := h.sessions[sessionID]
	if !ok {
		return sessionbackend.SessionRef{}, sessionbackend.ErrSessionNotFound
	}
	win, pane := h.activePaneLocked(s)
	ref := sessionbackend.SessionRef{
		SessionID:      s.id,
		Label:          s.label,
		Backend:        sessionbackend.BackendNative,
		HostInstanceID: h.hostID,
		Reused:         reused,
	}
	if win != nil {
		ref.WindowID = win.ID
	}
	if pane != nil {
		ref.PaneID = pane.id
		ref.RunGeneration = pane.paneGen
		ref.PID = pane.term.PID()
		ref.ProcessID = pane.processID
	}
	return ref, nil
}

func (h *Host) spawnPane(ctx context.Context, sessionID, paneID string, spec terminal.LaunchSpec) (*managedPane, error) {
	hasEnv := func(prefix string) bool {
		for _, kv := range spec.Env {
			if strings.HasPrefix(kv, prefix) {
				return true
			}
		}
		return false
	}
	if !hasEnv("ROAMI_SESSION=") {
		spec.Env = append(spec.Env, "ROAMI_SESSION="+sessionID)
	}
	if !hasEnv("ROAMI_PANE=") {
		spec.Env = append(spec.Env, "ROAMI_PANE="+paneID)
	}
	term, err := h.backend.Start(ctx, spec)
	if err != nil {
		return nil, err
	}
	procID := ""
	if insp, ok := h.backend.(terminal.ProcessInspector); ok {
		procID, _ = insp.ProcessIdentity(term.PID())
	}
	logPath := ""
	if h.logsDir != "" {
		logPath = filepath.Join(h.logsDir, sessionID+".log")
	}
	cols, rows := spec.Cols, spec.Rows
	if cols == 0 {
		cols = terminal.DefaultCols
	}
	if rows == 0 {
		rows = terminal.DefaultRows
	}
	return newManagedPane(sessionID, paneID, int64(h.seq.Add(1)), term, procID, spec.Cwd, logPath, cols, rows), nil
}

func (h *Host) activePaneLocked(s *managedSession) (*sessionbackend.Window, *managedPane) {
	for i := range s.windows {
		if s.windows[i].ID == s.activeWindowID {
			w := &s.windows[i]
			return w, s.panes[w.ActivePaneID]
		}
	}
	if len(s.windows) > 0 {
		w := &s.windows[0]
		return w, s.panes[w.ActivePaneID]
	}
	return nil, nil
}

func (h *Host) resolvePane(target sessionbackend.Target) (*managedPane, error) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	s, ok := h.sessions[target.SessionID]
	if !ok {
		return nil, sessionbackend.ErrSessionNotFound
	}
	if target.PaneID != "" {
		p, ok := s.panes[target.PaneID]
		if !ok {
			return nil, sessionbackend.ErrPaneNotFound
		}
		return p, nil
	}
	if target.WindowID != "" {
		for i := range s.windows {
			if s.windows[i].ID == target.WindowID {
				p := s.panes[s.windows[i].ActivePaneID]
				if p == nil {
					return nil, sessionbackend.ErrPaneNotFound
				}
				return p, nil
			}
		}
		return nil, sessionbackend.ErrWindowNotFound
	}
	_, p := h.activePaneLocked(s)
	if p == nil {
		return nil, sessionbackend.ErrPaneNotFound
	}
	return p, nil
}

func (h *Host) Observe(_ context.Context, sessionID string) (sessionbackend.SessionState, error) {
	h.mu.RLock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.RUnlock()
		return sessionbackend.SessionState{
			SessionID:      sessionID,
			Backend:        sessionbackend.BackendNative,
			HostInstanceID: h.hostID,
			Status:         sessionbackend.StatusExited,
		}, sessionbackend.ErrSessionNotFound
	}
	wins := make([]sessionbackend.Window, len(s.windows))
	for i := range s.windows {
		wins[i] = s.windows[i].Clone()
	}
	_, activePane := h.activePaneLocked(s)
	panes := make([]*managedPane, 0, len(s.panes))
	for _, p := range s.panes {
		panes = append(panes, p)
	}
	state := sessionbackend.SessionState{
		SessionID:      s.id,
		Label:          s.label,
		Backend:        sessionbackend.BackendNative,
		HostInstanceID: h.hostID,
		ActiveWindowID: s.activeWindowID,
		Windows:        wins,
		Cwd:            s.dir,
		CreatedAt:      s.createdAt,
		LastActivityAt: s.createdAt,
	}
	h.mu.RUnlock()

	anyAlive := false
	totalAttached := 0
	var lastExit *terminal.ExitResult
	for _, p := range panes {
		alive, exit, att, act := p.status()
		totalAttached += att
		if act.After(state.LastActivityAt) {
			state.LastActivityAt = act
		}
		if alive {
			anyAlive = true
		} else {
			ex := exit
			lastExit = &ex
		}
	}
	state.Attached = totalAttached
	if activePane != nil {
		state.ActivePaneID = activePane.id
		state.PID = activePane.term.PID()
		state.ProcessID = activePane.processID
		if c := activePane.cwd(); c != "" {
			state.Cwd = c
		}
	}
	if anyAlive {
		state.Status = sessionbackend.StatusAlive
	} else {
		state.Status = sessionbackend.StatusExited
		if lastExit != nil {
			code := lastExit.ExitCode
			state.ExitCode = &code
			state.Signal = lastExit.Signal
			if lastExit.Unknown {
				state.Status = sessionbackend.StatusUnknown
				state.Reason = lastExit.Reason
			}
		}
	}
	return state, nil
}

func (h *Host) List(ctx context.Context) ([]sessionbackend.SessionSummary, error) {
	h.mu.RLock()
	ids := make([]string, 0, len(h.sessions))
	for id := range h.sessions {
		ids = append(ids, id)
	}
	h.mu.RUnlock()
	sort.Strings(ids)

	out := make([]sessionbackend.SessionSummary, 0, len(ids))
	for _, id := range ids {
		st, err := h.Observe(ctx, id)
		if err != nil {
			continue
		}
		out = append(out, sessionbackend.SessionSummary{
			ID:             st.SessionID,
			Label:          st.Label,
			Backend:        st.Backend,
			HostInstanceID: st.HostInstanceID,
			Status:         st.Status,
			Windows:        len(st.Windows),
			CreatedAt:      st.CreatedAt,
			LastActivityAt: st.LastActivityAt,
			Attached:       st.Attached,
			Dir:            st.Cwd,
		})
	}
	return out, nil
}

func (h *Host) Close(ctx context.Context, sessionID string) error {
	h.mu.Lock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.Unlock()
		return sessionbackend.ErrSessionNotFound
	}
	delete(h.sessions, sessionID)
	panes := make([]*managedPane, 0, len(s.panes))
	for _, p := range s.panes {
		panes = append(panes, p)
	}
	h.mu.Unlock()

	var firstErr error
	for _, p := range panes {
		if err := p.terminate(ctx); err != nil && firstErr == nil {
			firstErr = err
		}
	}
	return firstErr
}

func (h *Host) Rename(_ context.Context, sessionID, label string) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	s, ok := h.sessions[sessionID]
	if !ok {
		return sessionbackend.ErrSessionNotFound
	}
	s.label = label
	return nil
}

func (h *Host) Attach(_ context.Context, target sessionbackend.Target, opts sessionbackend.AttachOpts) (sessionbackend.PaneStream, error) {
	p, err := h.resolvePane(target)
	if err != nil {
		return nil, err
	}
	return p.attach(opts), nil
}

func (h *Host) ClaimControl(_ context.Context, target sessionbackend.Target, clientID string) (sessionbackend.ControlLease, error) {
	p, err := h.resolvePane(target)
	if err != nil {
		return sessionbackend.ControlLease{}, err
	}
	return p.claimControl(clientID), nil
}

func (h *Host) ReleaseControl(_ context.Context, target sessionbackend.Target, clientID string, controlGen uint64) error {
	p, err := h.resolvePane(target)
	if err != nil {
		return err
	}
	return p.releaseControl(clientID, controlGen)
}

func (h *Host) WriteInput(_ context.Context, target sessionbackend.Target, controlGen uint64, data []byte) error {
	p, err := h.resolvePane(target)
	if err != nil {
		return err
	}
	return p.writeInput(controlGen, data)
}

func (h *Host) Submit(_ context.Context, target sessionbackend.Target, req sessionbackend.SubmitReq) (sessionbackend.SubmitReceipt, error) {
	p, err := h.resolvePane(target)
	if err != nil {
		return sessionbackend.SubmitReceipt{}, err
	}
	return p.submit(req)
}

func (h *Host) Resize(_ context.Context, target sessionbackend.Target, controlGen uint64, cols, rows uint16) error {
	p, err := h.resolvePane(target)
	if err != nil {
		return err
	}
	return p.resize(controlGen, cols, rows)
}

func (h *Host) MoveCursor(_ context.Context, target sessionbackend.Target, controlGen uint64, col, row int) error {
	p, err := h.resolvePane(target)
	if err != nil {
		return err
	}
	return p.moveCursor(controlGen, col, row)
}

func (h *Host) Capture(_ context.Context, target sessionbackend.Target, opts sessionbackend.CaptureOpts) (sessionbackend.CaptureResult, error) {
	p, err := h.resolvePane(target)
	if err != nil {
		return sessionbackend.CaptureResult{}, err
	}
	return p.capture(opts), nil
}

// ── LayoutBackend (multi-window and horizontal/vertical split support) ──────

func (h *Host) NewWindow(ctx context.Context, sessionID string, spec sessionbackend.WindowSpec) (sessionbackend.Window, error) {
	h.mu.RLock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.RUnlock()
		return sessionbackend.Window{}, sessionbackend.ErrSessionNotFound
	}
	defaultDir := s.dir
	h.mu.RUnlock()

	dir := spec.Dir
	if dir == "" {
		dir = defaultDir
	}
	winID := h.nextID("w")
	nodeID := h.nextID("n")
	paneID := h.nextID("p")
	pane, err := h.spawnPane(ctx, sessionID, paneID, terminal.LaunchSpec{
		Exe: spec.Exe, Args: spec.Args, Cwd: dir, Env: spec.Env,
		Cols: spec.Cols, Rows: spec.Rows, LoginShell: spec.LoginShell,
	})
	if err != nil {
		return sessionbackend.Window{}, err
	}

	name := spec.Name
	if name == "" {
		name = winID
	}
	win := sessionbackend.NewSinglePaneWindow(winID, name, nodeID, paneID)

	h.mu.Lock()
	s, ok = h.sessions[sessionID]
	if !ok {
		h.mu.Unlock()
		_ = pane.terminate(context.Background())
		return sessionbackend.Window{}, sessionbackend.ErrSessionNotFound
	}
	s.panes[paneID] = pane
	s.windows = append(s.windows, win)
	s.activeWindowID = winID
	updated := win.Clone()
	notify := make([]*managedPane, 0, len(s.panes))
	for _, p := range s.panes {
		notify = append(notify, p)
	}
	h.mu.Unlock()
	for _, p := range notify {
		p.broadcastLayout(updated)
	}
	return updated, nil
}

func (h *Host) ListWindows(_ context.Context, sessionID string) ([]sessionbackend.Window, error) {
	h.mu.RLock()
	defer h.mu.RUnlock()
	s, ok := h.sessions[sessionID]
	if !ok {
		return nil, sessionbackend.ErrSessionNotFound
	}
	out := make([]sessionbackend.Window, len(s.windows))
	for i := range s.windows {
		out[i] = s.windows[i].Clone()
	}
	return out, nil
}

func (h *Host) SelectWindow(_ context.Context, sessionID, windowID string) error {
	h.mu.Lock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.Unlock()
		return sessionbackend.ErrSessionNotFound
	}
	var updated sessionbackend.Window
	found := false
	for i := range s.windows {
		if s.windows[i].ID == windowID {
			s.activeWindowID = windowID
			updated = s.windows[i].Clone()
			found = true
			break
		}
	}
	if !found {
		h.mu.Unlock()
		return sessionbackend.ErrWindowNotFound
	}
	notify := make([]*managedPane, 0, len(s.panes))
	for _, p := range s.panes {
		notify = append(notify, p)
	}
	h.mu.Unlock()
	for _, p := range notify {
		p.broadcastLayout(updated)
	}
	return nil
}

func (h *Host) CloseWindow(ctx context.Context, sessionID, windowID string) error {
	h.mu.Lock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.Unlock()
		return sessionbackend.ErrSessionNotFound
	}
	idx := -1
	for i := range s.windows {
		if s.windows[i].ID == windowID {
			idx = i
			break
		}
	}
	if idx < 0 {
		h.mu.Unlock()
		return sessionbackend.ErrWindowNotFound
	}
	paneIDs := s.windows[idx].Layout.PaneIDs()
	var toStop []*managedPane
	for _, pid := range paneIDs {
		if p := s.panes[pid]; p != nil {
			toStop = append(toStop, p)
			delete(s.panes, pid)
		}
	}
	s.windows = append(s.windows[:idx], s.windows[idx+1:]...)
	var updated *sessionbackend.Window
	var notify []*managedPane
	if len(s.windows) == 0 {
		delete(h.sessions, sessionID)
	} else {
		if s.activeWindowID == windowID {
			nextIdx := idx
			if nextIdx >= len(s.windows) {
				nextIdx = len(s.windows) - 1
			}
			s.activeWindowID = s.windows[nextIdx].ID
		}
		for i := range s.windows {
			if s.windows[i].ID == s.activeWindowID {
				cp := s.windows[i].Clone()
				updated = &cp
				break
			}
		}
		for _, p := range s.panes {
			notify = append(notify, p)
		}
	}
	h.mu.Unlock()

	for _, p := range toStop {
		_ = p.terminate(ctx)
	}
	if updated != nil {
		for _, p := range notify {
			p.broadcastLayout(*updated)
		}
	}
	return nil
}

func (h *Host) SplitPane(ctx context.Context, sessionID, paneID string, spec sessionbackend.SplitSpec) (sessionbackend.Window, string, error) {
	h.mu.RLock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.RUnlock()
		return sessionbackend.Window{}, "", sessionbackend.ErrSessionNotFound
	}
	if paneID == "" {
		if _, p := h.activePaneLocked(s); p != nil {
			paneID = p.id
		}
	}
	origPane := s.panes[paneID]
	if origPane == nil {
		h.mu.RUnlock()
		return sessionbackend.Window{}, "", sessionbackend.ErrPaneNotFound
	}
	defaultDir := origPane.cwd()
	h.mu.RUnlock()

	cwd := spec.Cwd
	if cwd == "" {
		cwd = defaultDir
	}
	newPaneID := h.nextID("p")
	splitNodeID := h.nextID("s")
	leafNodeID := h.nextID("n")
	newPane, err := h.spawnPane(ctx, sessionID, newPaneID, terminal.LaunchSpec{
		Exe: spec.Exe, Args: spec.Args, Cwd: cwd, Env: spec.Env,
		Cols: spec.Cols, Rows: spec.Rows, LoginShell: spec.LoginShell,
	})
	if err != nil {
		return sessionbackend.Window{}, "", err
	}

	h.mu.Lock()
	s, ok = h.sessions[sessionID]
	if !ok {
		h.mu.Unlock()
		_ = newPane.terminate(context.Background())
		return sessionbackend.Window{}, "", sessionbackend.ErrSessionNotFound
	}
	var updated sessionbackend.Window
	var notify []*managedPane
	found := false
	for i := range s.windows {
		if s.windows[i].Layout.ContainsPane(paneID) {
			if err := s.windows[i].Split(paneID, spec.Dir, spec.Ratio, splitNodeID, leafNodeID, newPaneID); err != nil {
				h.mu.Unlock()
				_ = newPane.terminate(context.Background())
				return sessionbackend.Window{}, "", err
			}
			s.panes[newPaneID] = newPane
			updated = s.windows[i].Clone()
			for _, pid := range updated.Layout.PaneIDs() {
				if p := s.panes[pid]; p != nil {
					notify = append(notify, p)
				}
			}
			found = true
			break
		}
	}
	h.mu.Unlock()
	if !found {
		_ = newPane.terminate(context.Background())
		return sessionbackend.Window{}, "", sessionbackend.ErrPaneNotFound
	}
	for _, p := range notify {
		p.broadcastLayout(updated)
	}
	return updated, newPaneID, nil
}

func (h *Host) ResizeSplit(_ context.Context, sessionID, windowID, nodeID string, ratio float64, expectedVersion int64) (sessionbackend.Window, error) {
	h.mu.Lock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.Unlock()
		return sessionbackend.Window{}, sessionbackend.ErrSessionNotFound
	}
	var updated sessionbackend.Window
	var notify []*managedPane
	found := false
	for i := range s.windows {
		if s.windows[i].ID == windowID {
			if err := s.windows[i].ResizeSplit(nodeID, ratio, expectedVersion); err != nil {
				h.mu.Unlock()
				return sessionbackend.Window{}, err
			}
			updated = s.windows[i].Clone()
			for _, pid := range updated.Layout.PaneIDs() {
				if p := s.panes[pid]; p != nil {
					notify = append(notify, p)
				}
			}
			found = true
			break
		}
	}
	h.mu.Unlock()
	if !found {
		return sessionbackend.Window{}, sessionbackend.ErrWindowNotFound
	}
	for _, p := range notify {
		p.broadcastLayout(updated)
	}
	return updated, nil
}

func (h *Host) FocusPane(_ context.Context, sessionID, windowID, paneID string) (sessionbackend.Window, error) {
	h.mu.Lock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.Unlock()
		return sessionbackend.Window{}, sessionbackend.ErrSessionNotFound
	}
	var updated sessionbackend.Window
	var notify []*managedPane
	found := false
	for i := range s.windows {
		if (windowID == "" || s.windows[i].ID == windowID) && s.windows[i].Layout.ContainsPane(paneID) {
			s.windows[i].ActivePaneID = paneID
			s.windows[i].Version++
			s.activeWindowID = s.windows[i].ID
			updated = s.windows[i].Clone()
			for _, pid := range updated.Layout.PaneIDs() {
				if p := s.panes[pid]; p != nil {
					notify = append(notify, p)
				}
			}
			found = true
			break
		}
	}
	h.mu.Unlock()
	if !found {
		return sessionbackend.Window{}, sessionbackend.ErrPaneNotFound
	}
	for _, p := range notify {
		p.broadcastLayout(updated)
	}
	return updated, nil
}

func (h *Host) ClosePane(ctx context.Context, sessionID, paneID string) (*sessionbackend.Window, error) {
	h.mu.Lock()
	s, ok := h.sessions[sessionID]
	if !ok {
		h.mu.Unlock()
		return nil, sessionbackend.ErrSessionNotFound
	}
	pane := s.panes[paneID]
	if pane == nil {
		h.mu.Unlock()
		return nil, sessionbackend.ErrPaneNotFound
	}
	var updated *sessionbackend.Window
	var notify []*managedPane
	for i := range s.windows {
		if !s.windows[i].Layout.ContainsPane(paneID) {
			continue
		}
		empty, err := s.windows[i].RemovePane(paneID)
		if err != nil {
			h.mu.Unlock()
			return nil, err
		}
		delete(s.panes, paneID)
		if empty {
			winID := s.windows[i].ID
			s.windows = append(s.windows[:i], s.windows[i+1:]...)
			if len(s.windows) == 0 {
				delete(h.sessions, sessionID)
			} else {
				if s.activeWindowID == winID {
					nextIdx := i
					if nextIdx >= len(s.windows) {
						nextIdx = len(s.windows) - 1
					}
					s.activeWindowID = s.windows[nextIdx].ID
				}
				for j := range s.windows {
					if s.windows[j].ID == s.activeWindowID {
						cp := s.windows[j].Clone()
						updated = &cp
						break
					}
				}
				for _, p := range s.panes {
					notify = append(notify, p)
				}
			}
		} else {
			cp := s.windows[i].Clone()
			updated = &cp
			for _, pid := range cp.Layout.PaneIDs() {
				if p := s.panes[pid]; p != nil {
					notify = append(notify, p)
				}
			}
		}
		break
	}
	h.mu.Unlock()

	_ = pane.terminate(ctx)
	if updated != nil {
		for _, p := range notify {
			p.broadcastLayout(*updated)
		}
	}
	return updated, nil
}

// Shutdown terminates all panes owned by this host.
func (h *Host) Shutdown(ctx context.Context) {
	h.mu.Lock()
	var panes []*managedPane
	for id, s := range h.sessions {
		for _, p := range s.panes {
			panes = append(panes, p)
		}
		delete(h.sessions, id)
	}
	h.mu.Unlock()
	for _, p := range panes {
		_ = p.terminate(ctx)
	}
}
