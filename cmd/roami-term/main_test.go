//go:build linux || darwin

package main

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionipc"
)

// TestDualInstanceTermIsolation verifies two standalone roami-term daemons run in full
// isolation: terminating instance A leaves instance B's socket, session, and PTY untouched.
func TestDualInstanceTermIsolation(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	bin := filepath.Join(t.TempDir(), "roami-term")
	build := exec.CommandContext(ctx, "go", "build", "-o", bin, ".")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build roami-term failed: %v\n%s", err, string(out))
	}

	rootA := t.TempDir()
	rootB := t.TempDir()
	pidA, err := sessionipc.SpawnDetached(bin, "--instance-root", rootA, "--host-id", "inst-a")
	if err != nil {
		t.Fatalf("spawn A failed: %v", err)
	}
	pidB, err := sessionipc.SpawnDetached(bin, "--instance-root", rootB, "--host-id", "inst-b")
	if err != nil {
		_ = syscall.Kill(pidA, syscall.SIGKILL)
		t.Fatalf("spawn B failed: %v", err)
	}
	t.Cleanup(func() {
		_ = syscall.Kill(pidA, syscall.SIGKILL)
		_ = syscall.Kill(pidB, syscall.SIGKILL)
	})

	descA := waitForDescriptor(t, filepath.Join(rootA, "hosts", "inst-a.json"))
	descB := waitForDescriptor(t, filepath.Join(rootB, "hosts", "inst-b.json"))

	cliA, err := sessionipc.Dial(ctx, descA)
	if err != nil {
		t.Fatalf("dial A: %v", err)
	}
	defer cliA.CloseConn()
	cliB, err := sessionipc.Dial(ctx, descB)
	if err != nil {
		t.Fatalf("dial B: %v", err)
	}
	defer cliB.CloseConn()

	refA, err := cliA.Create(ctx, sessionbackend.CreateSpec{Label: "a", Exe: "/bin/sh"})
	if err != nil {
		t.Fatalf("create A: %v", err)
	}
	refB, err := cliB.Create(ctx, sessionbackend.CreateSpec{Label: "b", Exe: "/bin/sh"})
	if err != nil {
		t.Fatalf("create B: %v", err)
	}

	// Close session A, send SIGTERM to daemon A -> A drains and exits cleanly.
	if err := cliA.Close(ctx, refA.SessionID); err != nil {
		t.Fatalf("close A: %v", err)
	}
	_ = cliA.CloseConn()
	_ = syscall.Kill(pidA, syscall.SIGTERM)

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if err := syscall.Kill(pidA, 0); err != nil {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	// Instance B must still be 100% alive, interactive, and isolated!
	if err := cliB.WriteInput(ctx, sessionbackend.Target{SessionID: refB.SessionID}, 0, []byte("echo B_STILL_ALIVE\n")); err != nil {
		t.Fatalf("write to B after stopping A failed: %v", err)
	}
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		capRes, err := cliB.Capture(ctx, sessionbackend.Target{SessionID: refB.SessionID}, sessionbackend.CaptureOpts{Lines: 20})
		if err == nil && strings.Contains(capRes.Text, "B_STILL_ALIVE") {
			break
		}
		time.Sleep(30 * time.Millisecond)
	}
	capRes, _ := cliB.Capture(ctx, sessionbackend.Target{SessionID: refB.SessionID}, sessionbackend.CaptureOpts{Lines: 20})
	if !strings.Contains(capRes.Text, "B_STILL_ALIVE") {
		t.Fatalf("instance B did not echo B_STILL_ALIVE; got %q", capRes.Text)
	}

	// Cleanly shut down B via drain.
	_ = cliB.Close(ctx, refB.SessionID)
	_ = cliB.CloseConn()
	_ = syscall.Kill(pidB, syscall.SIGTERM)
	if _, err := os.Stat(descA.Address); err == nil {
		t.Errorf("instance A socket %s was not cleaned up on exit", descA.Address)
	}
}

func waitForDescriptor(t *testing.T, path string) sessionipc.EndpointDescriptor {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if desc, err := sessionipc.ReadEndpointDescriptor(path); err == nil {
			return desc
		}
		time.Sleep(30 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for descriptor %s", path)
	return sessionipc.EndpointDescriptor{}
}
