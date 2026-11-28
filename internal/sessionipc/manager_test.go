//go:build linux || darwin

package sessionipc

import (
	"context"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
)

func TestManagerOnDemandSpawnAndRouter(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	bin := filepath.Join(t.TempDir(), "roami-term")
	build := exec.CommandContext(ctx, "go", "build", "-o", bin, "../../cmd/roami-term")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build roami-term failed: %v\n%s", err, string(out))
	}

	root := t.TempDir()
	mgr := NewManager(root, bin)
	defer mgr.Close()

	router, err := mgr.Router(ctx, nil)
	if err != nil {
		t.Fatalf("Manager.Router on-demand spawn failed: %v", err)
	}
	cli, ptr, err := mgr.ConnectActive(ctx)
	if err != nil || ptr.CurrentHost == "" {
		t.Fatalf("ConnectActive failed: ptr=%+v err=%v", ptr, err)
	}
	t.Cleanup(func() {
		if desc, err := ReadEndpointDescriptor(filepath.Join(root, "hosts", ptr.CurrentHost+".json")); err == nil && desc.PID > 0 {
			_ = syscall.Kill(desc.PID, syscall.SIGKILL)
		}
	})

	ref, err := router.Create(ctx, sessionbackend.CreateSpec{
		Label: "auto-spawned",
		Exe:   "/bin/sh",
		Env:   []string{"ROAMI_AUTO=ok"},
	})
	if err != nil {
		t.Fatalf("Create via router failed: %v", err)
	}
	if err := router.WriteInput(ctx, sessionbackend.Target{SessionID: ref.SessionID}, 0, []byte("echo AUTO_$ROAMI_AUTO\n")); err != nil {
		t.Fatal(err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		capRes, err := router.Capture(ctx, sessionbackend.Target{SessionID: ref.SessionID}, sessionbackend.CaptureOpts{Lines: 20})
		if err == nil && strings.Contains(capRes.Text, "AUTO_ok") {
			break
		}
		time.Sleep(30 * time.Millisecond)
	}
	capRes, _ := router.Capture(ctx, sessionbackend.Target{SessionID: ref.SessionID}, sessionbackend.CaptureOpts{Lines: 20})
	if !strings.Contains(capRes.Text, "AUTO_ok") {
		t.Fatalf("expected AUTO_ok in capture, got %q", capRes.Text)
	}
	_ = cli.Close(ctx, ref.SessionID)
}
