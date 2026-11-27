package runtime

import (
	"context"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
)

// TmuxBackend adapts the existing tmux Runtime to the unified SessionBackend contract.
type TmuxBackend struct {
	rt Runtime
}

var _ sessionbackend.SessionBackend = (*TmuxBackend)(nil)

func NewBackend(rt Runtime) *TmuxBackend { return &TmuxBackend{rt: rt} }

func (r Runtime) Backend() *TmuxBackend { return NewBackend(r) }

func (b *TmuxBackend) Kind() sessionbackend.BackendKind { return sessionbackend.BackendTmux }

func (b *TmuxBackend) Capabilities() sessionbackend.CapabilitySet {
	return sessionbackend.CapabilitySet{
		Windows:        true,
		Splits:         true,
		MoveCursor:     true,
		ManagedSubmit:  true,
		MemoryLimit:    true,
		Pause:          true,
		ProcessInspect: true,
	}
}

func (b *TmuxBackend) withCtx(ctx context.Context) Runtime {
	rt := b.rt
	rt.Context = ctx
	return rt
}

func (b *TmuxBackend) Create(ctx context.Context, spec sessionbackend.CreateSpec) (sessionbackend.SessionRef, error) {
	rt := b.withCtx(ctx)
	opts := CreateOpts{
		ReservedName: spec.SessionID,
		OperationID:  spec.OperationID,
		Label:        spec.Label,
		Dir:          spec.Dir,
	}
	if spec.Cols > 0 {
		opts.Width = strconv.Itoa(int(spec.Cols))
	}
	if spec.Rows > 0 {
		opts.Height = strconv.Itoa(int(spec.Rows))
	}
	name, err := rt.CreateSession(opts)
	if err != nil {
		return sessionbackend.SessionRef{}, err
	}
	row := rt.SessionRow(name)
	return sessionbackend.SessionRef{
		SessionID: name,
		Label:     row.DisplayLabel(),
		Backend:   sessionbackend.BackendTmux,
	}, nil
}

func (b *TmuxBackend) Observe(ctx context.Context, sessionID string) (sessionbackend.SessionState, error) {
	rt := b.withCtx(ctx)
	rows, err := rt.ObserveSessionRows()
	if err != nil {
		return sessionbackend.SessionState{
			SessionID: sessionID,
			Backend:   sessionbackend.BackendTmux,
			Status:    sessionbackend.StatusUnknown,
			Reason:    err.Error(),
		}, err
	}
	for _, row := range rows {
		if row.Name == sessionID {
			return sessionbackend.SessionState{
				SessionID: row.Name,
				Label:     row.DisplayLabel(),
				Backend:   sessionbackend.BackendTmux,
				Status:    sessionbackend.StatusAlive,
				CreatedAt: time.Unix(row.Created, 0),
			}, nil
		}
	}
	return sessionbackend.SessionState{
		SessionID: sessionID,
		Backend:   sessionbackend.BackendTmux,
		Status:    sessionbackend.StatusExited,
	}, sessionbackend.ErrSessionNotFound
}

func (b *TmuxBackend) List(ctx context.Context) ([]sessionbackend.SessionSummary, error) {
	rt := b.withCtx(ctx)
	rows, err := rt.ObserveSessionRows()
	if err != nil {
		return nil, err
	}
	out := make([]sessionbackend.SessionSummary, 0, len(rows))
	for _, row := range rows {
		out = append(out, sessionbackend.SessionSummary{
			ID:        row.Name,
			Label:     row.DisplayLabel(),
			Backend:   sessionbackend.BackendTmux,
			Status:    sessionbackend.StatusAlive,
			Windows:   1,
			CreatedAt: time.Unix(row.Created, 0),
		})
	}
	return out, nil
}

func (b *TmuxBackend) Close(ctx context.Context, sessionID string) error {
	rt := b.withCtx(ctx)
	if !rt.HasSession(sessionID) {
		return sessionbackend.ErrSessionNotFound
	}
	return rt.Tmux("kill-session", "-t", "="+sessionID)
}

func (b *TmuxBackend) Rename(ctx context.Context, sessionID, label string) error {
	rt := b.withCtx(ctx)
	if !rt.HasSession(sessionID) {
		return sessionbackend.ErrSessionNotFound
	}
	return rt.SetSessionLabel(sessionID, label)
}

func (b *TmuxBackend) Attach(_ context.Context, _ sessionbackend.Target, _ sessionbackend.AttachOpts) (sessionbackend.PaneStream, error) {
	// Legacy tmux attach continues via backend/pty's tmux attach handler until drained.
	return nil, sessionbackend.ErrUnsupported
}

func (b *TmuxBackend) ClaimControl(_ context.Context, target sessionbackend.Target, clientID string) (sessionbackend.ControlLease, error) {
	return sessionbackend.ControlLease{PaneID: target.PaneID, Controller: clientID, ControlGen: 1}, nil
}

func (b *TmuxBackend) ReleaseControl(_ context.Context, _ sessionbackend.Target, _ string, _ uint64) error {
	return nil
}

func (b *TmuxBackend) WriteInput(ctx context.Context, target sessionbackend.Target, _ uint64, data []byte) error {
	rt := b.withCtx(ctx)
	t := tmuxPaneTarget(target)
	return rt.Tmux("send-keys", "-t", t, "-l", "--", string(data))
}

func (b *TmuxBackend) Submit(ctx context.Context, target sessionbackend.Target, req sessionbackend.SubmitReq) (sessionbackend.SubmitReceipt, error) {
	rt := b.withCtx(ctx)
	t := tmuxPaneTarget(target)
	var err error
	if req.SubmitEnter {
		err = rt.SendPromptSubmit(t, req.Payload)
	} else {
		err = rt.PasteInput(t, req.Payload)
	}
	if err != nil {
		return sessionbackend.SubmitReceipt{}, err
	}
	return sessionbackend.SubmitReceipt{RequestID: req.RequestID, Accepted: true, At: time.Now()}, nil
}

func (b *TmuxBackend) Resize(_ context.Context, _ sessionbackend.Target, _ uint64, _, _ uint16) error {
	return sessionbackend.ErrUnsupported
}

func (b *TmuxBackend) MoveCursor(_ context.Context, _ sessionbackend.Target, _ uint64, _, _ int) error {
	return sessionbackend.ErrUnsupported
}

func (b *TmuxBackend) Capture(ctx context.Context, target sessionbackend.Target, opts sessionbackend.CaptureOpts) (sessionbackend.CaptureResult, error) {
	rt := b.withCtx(ctx)
	lines := opts.Lines
	if lines <= 0 {
		lines = 200
	}
	text, err := rt.ReadCapture(target.SessionID, strconv.Itoa(lines))
	if err != nil {
		return sessionbackend.CaptureResult{}, err
	}
	return sessionbackend.CaptureResult{Text: text}, nil
}

func tmuxPaneTarget(target sessionbackend.Target) string {
	if strings.HasPrefix(target.PaneID, "%") {
		return target.PaneID
	}
	return fmt.Sprintf("=%s:", target.SessionID)
}
