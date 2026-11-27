package application

import (
	"context"
	"fmt"
	"io"

	"github.com/ybz21/Roami/internal/session"
	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionstore"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

// SessionService shares domain operations without parsing or capturing CLI output.
type SessionService struct {
	rt      runtime.Runtime
	meta    *sessmeta.Store
	exclude map[string]bool
	backend sessionbackend.SessionBackend
}

func NewSessions(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool) SessionService {
	return SessionService{rt: rt, meta: meta, exclude: exclude, backend: rt.Backend()}
}

func NewSessionsWithBackend(rt runtime.Runtime, meta *sessmeta.Store, exclude map[string]bool, backend sessionbackend.SessionBackend) SessionService {
	if backend == nil {
		backend = rt.Backend()
	}
	return SessionService{rt: rt, meta: meta, exclude: exclude, backend: backend}
}

func (s SessionService) Backend() sessionbackend.SessionBackend {
	if s.backend != nil {
		return s.backend
	}
	return s.rt.Backend()
}

func (s SessionService) Layout() (sessionbackend.LayoutBackend, bool) {
	lb, ok := s.Backend().(sessionbackend.LayoutBackend)
	return lb, ok
}

func (s SessionService) List(ctx context.Context) ([]session.Session, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	return session.Collect(s.rt, s.meta, s.exclude), nil
}

func (s SessionService) Create(ctx context.Context, opt runtime.CreateOpts, reuse bool) (session.CreateResult, error) {
	if err := ctx.Err(); err != nil {
		return session.CreateResult{}, err
	}
	return session.Create(s.rt, opt, reuse)
}

func (s SessionService) CreateWithSpec(ctx context.Context, spec sessionbackend.CreateSpec) (sessionbackend.SessionRef, error) {
	if err := ctx.Err(); err != nil {
		return sessionbackend.SessionRef{}, err
	}
	return s.Backend().Create(ctx, spec)
}

func (s SessionService) Observe(ctx context.Context, id string) (sessionbackend.SessionState, error) {
	if err := ctx.Err(); err != nil {
		return sessionbackend.SessionState{}, err
	}
	return s.Backend().Observe(ctx, id)
}

func (s SessionService) Rename(ctx context.Context, id, label string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if b := s.Backend(); b.Kind() != sessionbackend.BackendTmux {
		if err := b.Rename(ctx, id, label); err != nil {
			return err
		}
		if s.meta != nil {
			_ = s.meta.SetLabel(id, label)
		}
		return nil
	}
	_, _, err := session.Rename(s.rt, s.meta, nil, []string{id, label}, io.Discard)
	return err
}

func (s SessionService) Send(ctx context.Context, id, prompt string) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if b := s.Backend(); b.Kind() != sessionbackend.BackendTmux {
		_, err := b.Submit(ctx, sessionbackend.Target{SessionID: id}, sessionbackend.SubmitReq{
			Payload:        prompt,
			SubmitEnter:    true,
			BracketedPaste: true,
		})
		return err
	}
	return session.Send(s.rt, nil, []string{id, prompt}, io.Discard)
}

func (s SessionService) Kill(ctx context.Context, id string, cascade bool) error {
	if err := ctx.Err(); err != nil {
		return err
	}
	if b := s.Backend(); b.Kind() != sessionbackend.BackendTmux {
		if err := b.Close(ctx, id); err != nil {
			return err
		}
		if s.meta != nil {
			_ = s.meta.OnKill(id)
		}
		return nil
	}
	args := []string{id, "--yes"}
	if cascade {
		args = append(args, "--cascade")
	}
	return session.KillTree(s.rt, s.meta, s.exclude, args, io.Discard)
}

func (s SessionService) Capture(ctx context.Context, id, lines string) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	if b := s.Backend(); b.Kind() != sessionbackend.BackendTmux {
		var n int
		_, _ = fmt.Sscanf(lines, "%d", &n)
		res, err := b.Capture(ctx, sessionbackend.Target{SessionID: id}, sessionbackend.CaptureOpts{Lines: n, IncludeHistory: true})
		return res.Text, err
	}
	return s.rt.ReadCapture(s.rt.Resolve(id), lines)
}

func (s SessionService) Resolve(id string) (map[string]string, error) {
	name := s.rt.Resolve(id)
	if !s.rt.HasSession(name) {
		return nil, fmt.Errorf("session not found: %s", id)
	}
	row := s.rt.SessionRow(name)
	return map[string]string{"name": row.Name, "label": row.DisplayLabel(), "id": row.ID(), "tmux_id": row.TmuxID}, nil
}
