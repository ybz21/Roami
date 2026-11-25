package sessionbackend

import (
	"context"
	"errors"
	"testing"
)

type stubBackend struct {
	kind     BackendKind
	sessions map[string]string
	failList bool
}

func (s *stubBackend) Kind() BackendKind           { return s.kind }
func (s *stubBackend) Capabilities() CapabilitySet { return CapabilitySet{} }
func (s *stubBackend) Create(_ context.Context, spec CreateSpec) (SessionRef, error) {
	id := spec.SessionID
	if id == "" {
		id = string(s.kind) + "-1"
	}
	s.sessions[id] = spec.Label
	return SessionRef{SessionID: id, Label: spec.Label, Backend: s.kind}, nil
}
func (s *stubBackend) Observe(_ context.Context, id string) (SessionState, error) {
	if label, ok := s.sessions[id]; ok {
		return SessionState{SessionID: id, Label: label, Backend: s.kind, Status: StatusAlive}, nil
	}
	return SessionState{SessionID: id, Backend: s.kind, Status: StatusExited}, ErrSessionNotFound
}
func (s *stubBackend) List(_ context.Context) ([]SessionSummary, error) {
	if s.failList {
		return nil, errors.New("host unreachable")
	}
	out := make([]SessionSummary, 0, len(s.sessions))
	for id, label := range s.sessions {
		out = append(out, SessionSummary{ID: id, Label: label, Backend: s.kind, Status: StatusAlive})
	}
	return out, nil
}
func (s *stubBackend) Close(_ context.Context, id string) error {
	delete(s.sessions, id)
	return nil
}
func (s *stubBackend) Rename(_ context.Context, id, label string) error {
	s.sessions[id] = label
	return nil
}
func (s *stubBackend) Attach(_ context.Context, _ Target, _ AttachOpts) (PaneStream, error) {
	return nil, ErrUnsupported
}
func (s *stubBackend) ClaimControl(_ context.Context, _ Target, _ string) (ControlLease, error) {
	return ControlLease{}, nil
}
func (s *stubBackend) ReleaseControl(_ context.Context, _ Target, _ string, _ uint64) error {
	return nil
}
func (s *stubBackend) WriteInput(_ context.Context, _ Target, _ uint64, _ []byte) error { return nil }
func (s *stubBackend) Submit(_ context.Context, _ Target, _ SubmitReq) (SubmitReceipt, error) {
	return SubmitReceipt{}, nil
}
func (s *stubBackend) Resize(_ context.Context, _ Target, _ uint64, _, _ uint16) error { return nil }
func (s *stubBackend) MoveCursor(_ context.Context, _ Target, _ uint64, _, _ int) error {
	return nil
}
func (s *stubBackend) Capture(_ context.Context, target Target, _ CaptureOpts) (CaptureResult, error) {
	return CaptureResult{Text: string(s.kind) + ":" + target.SessionID}, nil
}

func TestRouterDualBackendAndPartialHostFailure(t *testing.T) {
	ctx := context.Background()
	oldTmux := &stubBackend{kind: BackendTmux, sessions: map[string]string{"legacy-1": "old"}}
	nativeNew := &stubBackend{kind: BackendNative, sessions: map[string]string{}}
	drainingDown := &stubBackend{kind: BackendNative, sessions: map[string]string{}, failList: true}

	router := NewRouter("native-v2", map[string]SessionBackend{
		"tmux":      oldTmux,
		"native-v2": nativeNew,
		"native-v1": drainingDown,
	})

	// Create goes to default backend (native-v2).
	ref, err := router.Create(ctx, CreateSpec{SessionID: "nat-1", Label: "new"})
	if err != nil || ref.Backend != BackendNative {
		t.Fatalf("Create = %+v err=%v", ref, err)
	}

	// List succeeds even when draining host is unreachable, returning both tmux and native-v2 sessions.
	rows, err := router.List(ctx)
	if err != nil || len(rows) != 2 {
		t.Fatalf("List = %+v err=%v", rows, err)
	}

	// Switching default back to tmux keeps existing native session routed to native-v2!
	if err := router.SetDefault("tmux"); err != nil {
		t.Fatal(err)
	}
	capNat, err := router.Capture(ctx, Target{SessionID: "nat-1"}, CaptureOpts{})
	if err != nil || capNat.Text != "native:nat-1" {
		t.Fatalf("Capture(nat-1) = %q err=%v", capNat.Text, err)
	}
	capLegacy, err := router.Capture(ctx, Target{SessionID: "legacy-1"}, CaptureOpts{})
	if err != nil || capLegacy.Text != "tmux:legacy-1" {
		t.Fatalf("Capture(legacy-1) = %q err=%v", capLegacy.Text, err)
	}
}
