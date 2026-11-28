package sessionbackend

import (
	"context"
	"fmt"
	"sort"
	"sync"
)

// Router dispatches new sessions to the configured default backend while routing existing
// sessions to whichever backend/host owns them (supporting tmux + multiple draining native hosts).
type Router struct {
	mu             sync.RWMutex
	defaultBackend string
	backends       map[string]SessionBackend
	owners         map[string]string // sessionID -> backendKey
}

var (
	_ SessionBackend = (*Router)(nil)
	_ LayoutBackend  = (*Router)(nil)
)

func NewRouter(defaultKey string, backends map[string]SessionBackend) *Router {
	cp := make(map[string]SessionBackend, len(backends))
	for k, v := range backends {
		cp[k] = v
	}
	return &Router{
		defaultBackend: defaultKey,
		backends:       cp,
		owners:         make(map[string]string),
	}
}

func (r *Router) Register(key string, backend SessionBackend) {
	r.mu.Lock()
	r.backends[key] = backend
	r.mu.Unlock()
}

func (r *Router) SetDefault(key string) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if _, ok := r.backends[key]; !ok {
		return fmt.Errorf("sessionbackend: unknown default backend %q", key)
	}
	r.defaultBackend = key
	return nil
}

func (r *Router) BindSession(sessionID, backendKey string) {
	r.mu.Lock()
	r.owners[sessionID] = backendKey
	r.mu.Unlock()
}

func (r *Router) Kind() BackendKind {
	r.mu.RLock()
	b := r.backends[r.defaultBackend]
	r.mu.RUnlock()
	if b != nil {
		return b.Kind()
	}
	return BackendNative
}

func (r *Router) Capabilities() CapabilitySet {
	r.mu.RLock()
	b := r.backends[r.defaultBackend]
	r.mu.RUnlock()
	if b != nil {
		return b.Capabilities()
	}
	return CapabilitySet{}
}

func (r *Router) resolve(ctx context.Context, sessionID string) (string, SessionBackend, error) {
	r.mu.RLock()
	if key, ok := r.owners[sessionID]; ok {
		if b, exists := r.backends[key]; exists {
			r.mu.RUnlock()
			return key, b, nil
		}
	}
	// Fallback: probe registered backends when ownership isn't cached yet.
	keys := make([]string, 0, len(r.backends))
	for k := range r.backends {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	backends := make(map[string]SessionBackend, len(r.backends))
	for k, v := range r.backends {
		backends[k] = v
	}
	r.mu.RUnlock()

	for _, k := range keys {
		st, err := backends[k].Observe(ctx, sessionID)
		if err == nil && st.Status == StatusAlive {
			r.BindSession(sessionID, k)
			return k, backends[k], nil
		}
	}
	return "", nil, ErrSessionNotFound
}

func (r *Router) Create(ctx context.Context, spec CreateSpec) (SessionRef, error) {
	r.mu.RLock()
	key := r.defaultBackend
	b := r.backends[key]
	r.mu.RUnlock()
	if b == nil {
		return SessionRef{}, fmt.Errorf("sessionbackend: default backend %q not registered", key)
	}
	ref, err := b.Create(ctx, spec)
	if err != nil {
		return SessionRef{}, err
	}
	r.BindSession(ref.SessionID, key)
	return ref, nil
}

func (r *Router) Observe(ctx context.Context, sessionID string) (SessionState, error) {
	_, b, err := r.resolve(ctx, sessionID)
	if err != nil {
		return SessionState{SessionID: sessionID, Status: StatusExited}, err
	}
	return b.Observe(ctx, sessionID)
}

func (r *Router) List(ctx context.Context) ([]SessionSummary, error) {
	return r.list(ctx, "")
}

// ListByKind requires a complete snapshot of the selected backend kind.
func (r *Router) ListByKind(ctx context.Context, kind BackendKind) ([]SessionSummary, error) {
	return r.list(ctx, kind)
}

func (r *Router) list(ctx context.Context, kind BackendKind) ([]SessionSummary, error) {
	r.mu.RLock()
	entries := make(map[string]SessionBackend, len(r.backends))
	for k, v := range r.backends {
		entries[k] = v
	}
	r.mu.RUnlock()

	var all []SessionSummary
	var firstErr error
	succeeded := 0
	for k, b := range entries {
		if kind != "" && b.Kind() != kind {
			continue
		}
		rows, err := b.List(ctx)
		if err != nil {
			if firstErr == nil {
				firstErr = err
			}
			continue
		}
		succeeded++
		for _, row := range rows {
			r.BindSession(row.ID, k)
			all = append(all, row)
		}
	}
	if firstErr != nil && (kind != "" || succeeded == 0) {
		return nil, firstErr
	}
	sort.Slice(all, func(i, j int) bool { return all[i].ID < all[j].ID })
	return all, nil
}

func (r *Router) Close(ctx context.Context, sessionID string) error {
	_, b, err := r.resolve(ctx, sessionID)
	if err != nil {
		return err
	}
	return b.Close(ctx, sessionID)
}

func (r *Router) Rename(ctx context.Context, sessionID, label string) error {
	_, b, err := r.resolve(ctx, sessionID)
	if err != nil {
		return err
	}
	return b.Rename(ctx, sessionID, label)
}

func (r *Router) Attach(ctx context.Context, target Target, opts AttachOpts) (PaneStream, error) {
	_, b, err := r.resolve(ctx, target.SessionID)
	if err != nil {
		return nil, err
	}
	return b.Attach(ctx, target, opts)
}

func (r *Router) ClaimControl(ctx context.Context, target Target, clientID string) (ControlLease, error) {
	_, b, err := r.resolve(ctx, target.SessionID)
	if err != nil {
		return ControlLease{}, err
	}
	return b.ClaimControl(ctx, target, clientID)
}

func (r *Router) ReleaseControl(ctx context.Context, target Target, clientID string, controlGen uint64) error {
	_, b, err := r.resolve(ctx, target.SessionID)
	if err != nil {
		return err
	}
	return b.ReleaseControl(ctx, target, clientID, controlGen)
}

func (r *Router) WriteInput(ctx context.Context, target Target, controlGen uint64, data []byte) error {
	_, b, err := r.resolve(ctx, target.SessionID)
	if err != nil {
		return err
	}
	return b.WriteInput(ctx, target, controlGen, data)
}

func (r *Router) Submit(ctx context.Context, target Target, req SubmitReq) (SubmitReceipt, error) {
	_, b, err := r.resolve(ctx, target.SessionID)
	if err != nil {
		return SubmitReceipt{}, err
	}
	return b.Submit(ctx, target, req)
}

func (r *Router) Resize(ctx context.Context, target Target, controlGen uint64, cols, rows uint16) error {
	_, b, err := r.resolve(ctx, target.SessionID)
	if err != nil {
		return err
	}
	return b.Resize(ctx, target, controlGen, cols, rows)
}

func (r *Router) MoveCursor(ctx context.Context, target Target, controlGen uint64, col, row int) error {
	_, b, err := r.resolve(ctx, target.SessionID)
	if err != nil {
		return err
	}
	return b.MoveCursor(ctx, target, controlGen, col, row)
}

func (r *Router) Capture(ctx context.Context, target Target, opts CaptureOpts) (CaptureResult, error) {
	_, b, err := r.resolve(ctx, target.SessionID)
	if err != nil {
		return CaptureResult{}, err
	}
	return b.Capture(ctx, target, opts)
}

// ── LayoutBackend forwarding ────────────────────────────────────────────────

func (r *Router) resolveLayout(ctx context.Context, sessionID string) (LayoutBackend, error) {
	_, b, err := r.resolve(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	lb, ok := b.(LayoutBackend)
	if !ok {
		return nil, ErrUnsupported
	}
	return lb, nil
}

func (r *Router) NewWindow(ctx context.Context, sessionID string, spec WindowSpec) (Window, error) {
	lb, err := r.resolveLayout(ctx, sessionID)
	if err != nil {
		return Window{}, err
	}
	return lb.NewWindow(ctx, sessionID, spec)
}

func (r *Router) ListWindows(ctx context.Context, sessionID string) ([]Window, error) {
	lb, err := r.resolveLayout(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	return lb.ListWindows(ctx, sessionID)
}

func (r *Router) SelectWindow(ctx context.Context, sessionID, windowID string) error {
	lb, err := r.resolveLayout(ctx, sessionID)
	if err != nil {
		return err
	}
	return lb.SelectWindow(ctx, sessionID, windowID)
}

func (r *Router) CloseWindow(ctx context.Context, sessionID, windowID string) error {
	lb, err := r.resolveLayout(ctx, sessionID)
	if err != nil {
		return err
	}
	return lb.CloseWindow(ctx, sessionID, windowID)
}

func (r *Router) SplitPane(ctx context.Context, sessionID, paneID string, spec SplitSpec) (Window, string, error) {
	lb, err := r.resolveLayout(ctx, sessionID)
	if err != nil {
		return Window{}, "", err
	}
	return lb.SplitPane(ctx, sessionID, paneID, spec)
}

func (r *Router) ResizeSplit(ctx context.Context, sessionID, windowID, nodeID string, ratio float64, expectedVersion int64) (Window, error) {
	lb, err := r.resolveLayout(ctx, sessionID)
	if err != nil {
		return Window{}, err
	}
	return lb.ResizeSplit(ctx, sessionID, windowID, nodeID, ratio, expectedVersion)
}

func (r *Router) FocusPane(ctx context.Context, sessionID, windowID, paneID string) (Window, error) {
	lb, err := r.resolveLayout(ctx, sessionID)
	if err != nil {
		return Window{}, err
	}
	return lb.FocusPane(ctx, sessionID, windowID, paneID)
}

func (r *Router) ClosePane(ctx context.Context, sessionID, paneID string) (*Window, error) {
	lb, err := r.resolveLayout(ctx, sessionID)
	if err != nil {
		return nil, err
	}
	return lb.ClosePane(ctx, sessionID, paneID)
}
