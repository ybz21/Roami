package sessionipc

import (
	"context"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionhost"
)

func TestIPCClientServerEndToEndAndSplit(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	root := t.TempDir()
	host := sessionhost.NewHost(sessionhost.Config{
		HostID:  "ipc-host-1",
		LogsDir: filepath.Join(root, "logs"),
	})
	defer host.Shutdown(ctx)

	srv, err := NewServer(host, root)
	if err != nil {
		t.Fatalf("NewServer failed: %v", err)
	}
	defer srv.Close()

	if desc := srv.Descriptor(); desc.Network == "unix" && len(desc.Address) > 90 {
		t.Fatalf("unix socket path too long (%d bytes): %s", len(desc.Address), desc.Address)
	}

	go func() { _ = srv.Serve(ctx) }()

	// Invalid token must be rejected.
	badDesc := srv.Descriptor()
	badDesc.Token = "wrong-token"
	if _, err := Dial(ctx, badDesc); err == nil {
		t.Fatal("expected invalid token to be rejected")
	}

	client, err := Dial(ctx, srv.Descriptor())
	if err != nil {
		t.Fatalf("Dial failed: %v", err)
	}
	defer client.CloseConn()

	ref, err := client.Create(ctx, sessionbackend.CreateSpec{
		Label: "ipc-demo",
		Exe:   "/bin/sh",
		Env:   []string{"ROAMI_IPC_TEST=ok"},
		Cols:  80,
		Rows:  24,
	})
	if err != nil {
		t.Fatalf("Create over IPC failed: %v", err)
	}

	target := sessionbackend.Target{SessionID: ref.SessionID, PaneID: ref.PaneID}
	stream, err := client.Attach(ctx, target, sessionbackend.AttachOpts{ClientID: "cli-1"})
	if err != nil {
		t.Fatalf("Attach over IPC failed: %v", err)
	}

	ev := <-stream.Events()
	if ev.Kind != sessionbackend.EventSnapshot {
		t.Fatalf("expected initial snapshot event, got %s", ev.Kind)
	}

	lease, err := client.ClaimControl(ctx, target, "cli-1")
	if err != nil {
		t.Fatal(err)
	}
	if err := client.WriteInput(ctx, target, lease.ControlGen, []byte("echo IPC_$ROAMI_IPC_TEST\n")); err != nil {
		t.Fatal(err)
	}

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		capRes, err := client.Capture(ctx, target, sessionbackend.CaptureOpts{Lines: 30, IncludeHistory: true})
		if err == nil && strings.Contains(capRes.Text, "IPC_ok") {
			break
		}
		time.Sleep(30 * time.Millisecond)
	}
	capRes, _ := client.Capture(ctx, target, sessionbackend.CaptureOpts{Lines: 30, IncludeHistory: true})
	if !strings.Contains(capRes.Text, "IPC_ok") {
		t.Fatalf("expected IPC_ok in capture, got:\n%s", capRes.Text)
	}

	// Split horizontally over IPC -> client receives layout_changed event on stream!
	win, pane2, err := client.SplitPane(ctx, ref.SessionID, ref.PaneID, sessionbackend.SplitSpec{
		Dir: sessionbackend.SplitHorizontal, Ratio: 0.5, Exe: "/bin/sh",
	})
	if err != nil || pane2 == "" || len(win.Layout.PaneIDs()) != 2 {
		t.Fatalf("SplitPane over IPC failed: win=%+v pane2=%q err=%v", win, pane2, err)
	}

	// Disconnect client connection completely (simulating Web restart) -> session stays alive!
	_ = stream.Close()
	_ = client.CloseConn()

	client2, err := Dial(ctx, srv.Descriptor())
	if err != nil {
		t.Fatalf("reconnect Dial failed: %v", err)
	}
	defer client2.CloseConn()

	st, err := client2.Observe(ctx, ref.SessionID)
	if err != nil || st.Status != sessionbackend.StatusAlive || len(st.Windows) != 1 || len(st.Windows[0].Layout.PaneIDs()) != 2 {
		t.Fatalf("session did not survive client reconnect: st=%+v err=%v", st, err)
	}

	if err := client2.Close(ctx, ref.SessionID); err != nil {
		t.Fatalf("Close failed: %v", err)
	}
}
