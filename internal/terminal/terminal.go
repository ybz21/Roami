// Package terminal provides the cross-platform PTY and process boundary used by roami-term.
package terminal

import (
	"context"
	"errors"
	"io"
	"os"
	"runtime"
	"strings"
	"time"
)

var (
	ErrUnsupported = errors.New("terminal: operation unsupported on this platform")
	ErrClosed      = errors.New("terminal: already closed")
)

const (
	DefaultCols uint16 = 100
	DefaultRows uint16 = 30
	MinCols     uint16 = 20
	MinRows     uint16 = 6
)

// LaunchSpec describes a process to start attached to a fresh PTY/ConPTY.
type LaunchSpec struct {
	Exe        string
	Args       []string
	Cwd        string
	Env        []string
	Cols       uint16
	Rows       uint16
	LoginShell bool
}

// ExitResult distinguishes confirmed process exit from unknown observation failures.
type ExitResult struct {
	Exited   bool
	ExitCode int
	Signal   string
	Unknown  bool
	Reason   string
}

// Capabilities reports optional platform features so callers avoid runtime.GOOS branching.
type Capabilities struct {
	MemoryLimit    bool
	Pause          bool
	ProcessInspect bool
	CurrentDir     bool
	Signals        bool
}

// TerminalBackend is the core cross-platform PTY factory implemented identically on Linux, macOS, and Windows.
type TerminalBackend interface {
	Start(ctx context.Context, spec LaunchSpec) (Terminal, error)
	Capabilities() Capabilities
}

// Terminal is a running process bound to a platform PTY/ConPTY.
type Terminal interface {
	io.ReadWriteCloser
	PID() int
	Resize(cols, rows uint16) error
	Terminate(ctx context.Context, grace time.Duration) error
	Wait() (ExitResult, error)
}

// ProcessInspector provides OS-level process identity and working directory probes.
type ProcessInspector interface {
	ProcessIdentity(pid int) (string, error)
	CurrentDir(pid int) (string, error)
}

// ResourceGuard optionally enforces and reads per-pane memory limits (cgroup on Linux, Job on Windows).
type ResourceGuard interface {
	ApplyMemoryLimit(limitBytes int64) error
	MemoryUsage() (currentBytes, peakBytes int64, oomKills int64, ok bool)
}

// PauseController optionally freezes and resumes a pane's process group.
type PauseController interface {
	SetPaused(paused bool) error
}

// DefaultShell returns the platform's preferred interactive shell executable.
func DefaultShell() string {
	if runtime.GOOS == "windows" {
		return "pwsh.exe"
	}
	if sh := strings.TrimSpace(os.Getenv("SHELL")); sh != "" {
		return sh
	}
	if runtime.GOOS == "darwin" {
		return "/bin/zsh"
	}
	return "/bin/bash"
}

func normalizeSize(cols, rows uint16) (uint16, uint16) {
	if cols == 0 {
		cols = DefaultCols
	}
	if rows == 0 {
		rows = DefaultRows
	}
	if cols < MinCols {
		cols = MinCols
	}
	if rows < MinRows {
		rows = MinRows
	}
	return cols, rows
}

func mergeEnv(base, extra []string) []string {
	out := make([]string, 0, len(base)+len(extra)+2)
	index := make(map[string]int, len(base)+len(extra))
	put := func(kv string) {
		k, _, ok := strings.Cut(kv, "=")
		if !ok || k == "" {
			return
		}
		key := k
		if runtime.GOOS == "windows" {
			key = strings.ToUpper(k)
		}
		if pos, exists := index[key]; exists {
			out[pos] = kv
			return
		}
		index[key] = len(out)
		out = append(out, kv)
	}
	for _, kv := range base {
		put(kv)
	}
	for _, kv := range extra {
		put(kv)
	}
	if _, hasTerm := index["TERM"]; !hasTerm && runtime.GOOS != "windows" {
		put("TERM=xterm-256color")
	}
	return out
}

func ensureUTF8Locale(env []string) []string {
	get := func(k string) string {
		prefix := k + "="
		for i := len(env) - 1; i >= 0; i-- {
			if strings.HasPrefix(env[i], prefix) {
				return env[i][len(prefix):]
			}
		}
		return ""
	}
	eff := get("LC_ALL")
	if eff == "" {
		eff = get("LC_CTYPE")
	}
	if eff == "" {
		eff = get("LANG")
	}
	upper := strings.ToUpper(eff)
	if strings.Contains(upper, "UTF-8") || strings.Contains(upper, "UTF8") {
		return env
	}
	return append(env, "LC_ALL=C.UTF-8")
}
