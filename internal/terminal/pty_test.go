//go:build linux || darwin

package terminal

import (
	"bytes"
	"context"
	"io"
	"runtime"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestUnixTerminalContract(t *testing.T) {
	b := NewBackend()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	dir := t.TempDir()
	term, err := b.Start(ctx, LaunchSpec{
		Exe:  "/bin/sh",
		Cwd:  dir,
		Env:  []string{"ROAMI_TEST_ENV=你好跨端"},
		Cols: 80,
		Rows: 24,
	})
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}
	defer term.Close()

	if term.PID() <= 0 {
		t.Fatalf("expected positive PID, got %d", term.PID())
	}

	if insp, ok := b.(ProcessInspector); ok {
		id, err := insp.ProcessIdentity(term.PID())
		if err != nil || id == "" {
			t.Fatalf("ProcessIdentity failed: id=%q err=%v", id, err)
		}
		if runtime.GOOS == "linux" {
			gotDir, err := insp.CurrentDir(term.PID())
			if err != nil || gotDir != dir {
				t.Fatalf("CurrentDir = %q (err=%v), want %q", gotDir, err, dir)
			}
		}
	}

	var out bytes.Buffer
	doneRead := make(chan struct{})
	go func() {
		defer close(doneRead)
		_, _ = io.Copy(&out, term)
	}()

	if err := term.Resize(132, 32); err != nil {
		t.Fatalf("Resize failed: %v", err)
	}
	cmds := "test -t 0 && echo IS_TTY; stty size; echo ENV=$ROAMI_TEST_ENV; exit 7\n"
	if _, err := term.Write([]byte(cmds)); err != nil {
		t.Fatalf("Write failed: %v", err)
	}

	res, err := term.Wait()
	if err != nil {
		t.Fatalf("Wait error: %v", err)
	}
	if !res.Exited || res.ExitCode != 7 || res.Unknown {
		t.Fatalf("Wait result = %+v, want exit code 7", res)
	}

	select {
	case <-doneRead:
	case <-time.After(3 * time.Second):
		t.Fatalf("output did not drain to EOF after process exit; got %q", out.String())
	}

	got := out.String()
	for _, want := range []string{"IS_TTY", "32 132", "ENV=你好跨端"} {
		if !strings.Contains(got, want) {
			t.Errorf("output missing %q; full output:\n%s", want, got)
		}
	}

	// Idempotent Close.
	if err := term.Close(); err != nil {
		t.Fatalf("first Close failed: %v", err)
	}
	if err := term.Close(); err != nil {
		t.Fatalf("second Close failed: %v", err)
	}
}

func TestUnixTerminalTerminateProcessGroup(t *testing.T) {
	b := NewBackend()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	term, err := b.Start(ctx, LaunchSpec{
		Exe:  "/bin/sh",
		Args: []string{"-c", "sleep 30 & wait"},
		Cols: 80,
		Rows: 24,
	})
	if err != nil {
		t.Fatalf("Start failed: %v", err)
	}
	defer term.Close()

	time.Sleep(100 * time.Millisecond)
	if err := term.Terminate(ctx, 200*time.Millisecond); err != nil {
		t.Fatalf("Terminate failed: %v", err)
	}
	res, err := term.Wait()
	if err != nil {
		t.Fatalf("Wait failed: %v", err)
	}
	if !res.Exited {
		t.Fatalf("expected Exited=true, got %+v", res)
	}
	// Verify main process group is gone.
	if err := syscall.Kill(-term.PID(), 0); err == nil {
		t.Fatalf("process group -%d still alive after Terminate", term.PID())
	}
}
