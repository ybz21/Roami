//go:build linux || darwin

package terminal

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sync"
	"syscall"
	"time"

	creackpty "github.com/creack/pty"
)

// UnixBackend implements TerminalBackend using system PTYs via creack/pty.
type UnixBackend struct{}

// NewBackend returns the native TerminalBackend for the current operating system.
func NewBackend() TerminalBackend { return UnixBackend{} }

func (UnixBackend) Capabilities() Capabilities {
	return Capabilities{
		MemoryLimit:    runtime.GOOS == "linux",
		Pause:          runtime.GOOS == "linux",
		ProcessInspect: true,
		CurrentDir:     runtime.GOOS == "linux",
		Signals:        true,
	}
}

func (UnixBackend) Start(ctx context.Context, spec LaunchSpec) (Terminal, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	exe := spec.Exe
	args := append([]string(nil), spec.Args...)
	if exe == "" {
		exe = DefaultShell()
		if spec.LoginShell && len(args) == 0 {
			args = []string{"-l"}
		}
	}
	cmd := exec.Command(exe, args...)
	if spec.Cwd != "" {
		cmd.Dir = spec.Cwd
	}
	env := ensureUTF8Locale(mergeEnv(os.Environ(), spec.Env))
	cmd.Env = env
	if spec.LoginShell && len(args) == 0 {
		cmd.Args = []string{"-" + filepath.Base(exe)}
	}

	cols, rows := normalizeSize(spec.Cols, spec.Rows)
	ptmx, err := creackpty.StartWithSize(cmd, &creackpty.Winsize{Cols: cols, Rows: rows})
	if err != nil {
		return nil, fmt.Errorf("terminal: start unix pty: %w", err)
	}

	t := &unixTerminal{
		ptmx:     ptmx,
		cmd:      cmd,
		pid:      cmd.Process.Pid,
		waitDone: make(chan struct{}),
	}
	go t.reap()
	return t, nil
}

type unixTerminal struct {
	ptmx *os.File
	cmd  *exec.Cmd
	pid  int

	mu     sync.Mutex
	closed bool

	waitDone chan struct{}
	exit     ExitResult
	waitErr  error
}

func (t *unixTerminal) reap() {
	defer close(t.waitDone)
	err := t.cmd.Wait()
	if err == nil {
		t.exit = ExitResult{Exited: true, ExitCode: 0}
		return
	}
	var exitErr *exec.ExitError
	if errors.As(err, &exitErr) {
		ws, ok := exitErr.Sys().(syscall.WaitStatus)
		if ok && ws.Signaled() {
			t.exit = ExitResult{Exited: true, ExitCode: 128 + int(ws.Signal()), Signal: ws.Signal().String()}
			return
		}
		t.exit = ExitResult{Exited: true, ExitCode: exitErr.ExitCode()}
		return
	}
	t.exit = ExitResult{Unknown: true, Reason: err.Error()}
	t.waitErr = err
}

func (t *unixTerminal) PID() int { return t.pid }

func (t *unixTerminal) Read(p []byte) (int, error) {
	n, err := t.ptmx.Read(p)
	if err != nil {
		// Linux returns EIO on the master fd once the slave side closes.
		if errors.Is(err, syscall.EIO) {
			return n, io.EOF
		}
		return n, err
	}
	return n, nil
}

func (t *unixTerminal) Write(p []byte) (int, error) {
	t.mu.Lock()
	closed := t.closed
	t.mu.Unlock()
	if closed {
		return 0, ErrClosed
	}
	return t.ptmx.Write(p)
}

func (t *unixTerminal) Resize(cols, rows uint16) error {
	t.mu.Lock()
	closed := t.closed
	t.mu.Unlock()
	if closed {
		return ErrClosed
	}
	cols, rows = normalizeSize(cols, rows)
	return creackpty.Setsize(t.ptmx, &creackpty.Winsize{Cols: cols, Rows: rows})
}

func (t *unixTerminal) Terminate(ctx context.Context, grace time.Duration) error {
	if grace <= 0 {
		grace = 2 * time.Second
	}
	// creack/pty starts the child with Setsid, so -pid targets its entire session process group.
	_ = syscall.Kill(-t.pid, syscall.SIGTERM)
	timer := time.NewTimer(grace)
	defer timer.Stop()
	select {
	case <-t.waitDone:
	case <-timer.C:
	case <-ctx.Done():
	}
	// Ensure any remaining background children in the process group are also terminated.
	if syscall.Kill(-t.pid, 0) == nil {
		_ = syscall.Kill(-t.pid, syscall.SIGKILL)
		deadline := time.Now().Add(2 * time.Second)
		for time.Now().Before(deadline) {
			if syscall.Kill(-t.pid, 0) != nil {
				break
			}
			time.Sleep(10 * time.Millisecond)
		}
	}
	select {
	case <-t.waitDone:
		return nil
	case <-time.After(2 * time.Second):
		return fmt.Errorf("terminal: process %d did not exit after SIGKILL", t.pid)
	}
}

func (t *unixTerminal) Wait() (ExitResult, error) {
	<-t.waitDone
	return t.exit, t.waitErr
}

func (t *unixTerminal) Close() error {
	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		return nil
	}
	t.closed = true
	t.mu.Unlock()
	return t.ptmx.Close()
}
