package application

import (
	"context"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionhost"
	"github.com/ybz21/Roami/internal/sessionstore"
	runtime "github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestSessionServiceWithNativeBackendAndLayout(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	dir := t.TempDir()
	host := sessionhost.NewHost(sessionhost.Config{
		HostID:  "app-host-1",
		LogsDir: dir,
	})
	defer host.Shutdown(ctx)

	meta := sessmeta.New(dir)
	svc := NewSessionsWithBackend(runtime.Runtime{HomeDir: dir, DataDir: dir}, meta, nil, host)

	ref, err := svc.CreateWithSpec(ctx, sessionbackend.CreateSpec{
		Label: "svc-demo",
		Dir:   dir,
		Exe:   "/bin/sh",
		Env:   []string{"ROAMI_APP_OK=1"},
		Cols:  80,
		Rows:  24,
	})
	if err != nil {
		t.Fatalf("CreateWithSpec failed: %v", err)
	}
	if err := meta.Put(sessmeta.Row{Session: ref.SessionID, Backend: "native", HostInstanceID: ref.HostInstanceID, InitialCwd: dir}); err != nil {
		t.Fatalf("meta.Put failed: %v", err)
	}

	if err := svc.Send(ctx, ref.SessionID, "echo APP_TEST_$ROAMI_APP_OK"); err != nil {
		t.Fatalf("Send failed: %v", err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		out, err := svc.Capture(ctx, ref.SessionID, "30")
		if err == nil && strings.Contains(out, "APP_TEST_1") {
			break
		}
		time.Sleep(30 * time.Millisecond)
	}
	out, err := svc.Capture(ctx, ref.SessionID, "30")
	if err != nil || !strings.Contains(out, "APP_TEST_1") {
		t.Fatalf("Capture = %q err=%v", out, err)
	}

	if err := svc.Rename(ctx, ref.SessionID, "renamed-demo"); err != nil {
		t.Fatalf("Rename failed: %v", err)
	}
	st, err := svc.Observe(ctx, ref.SessionID)
	if err != nil || st.Label != "renamed-demo" || st.Status != sessionbackend.StatusAlive {
		t.Fatalf("Observe = %+v err=%v", st, err)
	}

	// Reserved LayoutBackend is accessible directly from SessionService.
	lb, ok := svc.Layout()
	if !ok {
		t.Fatal("expected native SessionService to expose LayoutBackend")
	}
	win, pane2, err := lb.SplitPane(ctx, ref.SessionID, ref.PaneID, sessionbackend.SplitSpec{
		Dir: sessionbackend.SplitHorizontal, Ratio: 0.5, Exe: "/bin/sh",
	})
	if err != nil || pane2 == "" || len(win.Layout.PaneIDs()) != 2 {
		t.Fatalf("SplitPane failed: win=%+v pane2=%q err=%v", win, pane2, err)
	}

	if err := svc.Kill(ctx, ref.SessionID, false); err != nil {
		t.Fatalf("Kill failed: %v", err)
	}
	if row, ok := meta.Get(ref.SessionID); !ok || row.Status != "dead" {
		t.Fatalf("expected meta row marked dead after Kill, got %+v", row)
	}
}
