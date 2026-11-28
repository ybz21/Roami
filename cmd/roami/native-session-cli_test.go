package main

import (
	"bytes"
	"io"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/cli/nativeattach"
	"github.com/ybz21/Roami/internal/procctl"
	"github.com/ybz21/Roami/internal/sessioncoord"
)

func TestNativeSessionCLIEndToEnd(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix shell integration test")
	}

	tmp := t.TempDir()
	sessiondBin := filepath.Join(tmp, "roami-sessiond")
	build := exec.Command("go", "build", "-o", sessiondBin, "../roami-sessiond")
	if out, err := build.CombinedOutput(); err != nil {
		t.Fatalf("build roami-sessiond: %v\n%s", err, out)
	}

	// Verify native PTY is the default on Unix without setting ROAMI_NATIVE_TERMINAL,
	// while --backend tmux and ROAMI_NATIVE_TERMINAL=0 still fall back cleanly to tmux.
	t.Setenv("ROAMI_NATIVE_TERMINAL", "")
	t.Setenv("ROAMI_SESSIOND_BIN", sessiondBin)
	t.Setenv("ROAMI_HOME", filepath.Join(tmp, "home"))
	t.Setenv("ROAMI_DATA", filepath.Join(tmp, "data"))
	t.Cleanup(func() {
		if coord, err := sessioncoord.Open(filepath.Join(tmp, "data", "session-host.db")); err == nil {
			defer coord.Close()
			if hosts, err := coord.ListHosts(); err == nil {
				for _, h := range hosts {
					if h.PID > 0 {
						_ = procctl.KillPID(h.PID, false)
					}
				}
			}
		}
	})

	run := func(cmd string, args ...string) (string, string, bool, int) {
		var out, errOut bytes.Buffer
		handled, code := dispatchNativeSessionCLI(cmd, args, bytes.NewReader(nil), &out, &errOut)
		return strings.TrimSpace(out.String()), strings.TrimSpace(errOut.String()), handled, code
	}

	// Explicit --backend tmux always stays on tmux (handled=false).
	if _, _, handled, _ := run("new", "--backend", "tmux", "plain-tmux"); handled {
		t.Fatalf("new --backend tmux should stay on tmux")
	}

	// ROAMI_NATIVE_TERMINAL=0 opts out to tmux on Unix.
	t.Setenv("ROAMI_NATIVE_TERMINAL", "0")
	if _, _, handled, _ := run("new", "optout-tmux"); handled {
		t.Fatalf("new with ROAMI_NATIVE_TERMINAL=0 should stay on tmux")
	}
	t.Setenv("ROAMI_NATIVE_TERMINAL", "")

	// Default `new` (without --backend or env var) creates on roami-sessiond.
	out, errOut, handled, code := run("new", "--size", "100x30", "--detach", "cli-e2e", "--", "/bin/sh")
	if !handled || code != 0 || out != "cli-e2e" {
		t.Fatalf("default new failed: handled=%v code=%d out=%q err=%q", handled, code, out, errOut)
	}
	defer func() {
		_, _, _, _ = run("kill", "cli-e2e")
	}()

	// Re-running `new --backend native` with the same name reuses the existing session by default.
	out, errOut, handled, code = run("new", "--backend", "native", "--detach", "cli-e2e")
	if !handled || code != 0 || out != "cli-e2e" {
		t.Fatalf("new reuse failed: handled=%v code=%d out=%q err=%q", handled, code, out, errOut)
	}

	// Rename and verify subsequent commands work by friendly label as well as ID.
	_, errOut, handled, code = run("rename", "cli-e2e", "friendly-cli")
	if !handled || code != 0 {
		t.Fatalf("rename failed: handled=%v code=%d err=%q", handled, code, errOut)
	}

	// Resolve native session by friendly label (plain and --strict --json).
	out, errOut, handled, code = run("resolve", "friendly-cli", "--strict")
	if !handled || code != 0 || out != "cli-e2e" {
		t.Fatalf("resolve --strict failed: handled=%v code=%d out=%q err=%q", handled, code, out, errOut)
	}
	out, errOut, handled, code = run("resolve", "friendly-cli", "--strict", "--json")
	if !handled || code != 0 || !strings.Contains(out, `"session":"cli-e2e"`) || !strings.Contains(out, `"backend":"native"`) {
		t.Fatalf("resolve --strict --json failed: handled=%v code=%d out=%q err=%q", handled, code, out, errOut)
	}

	// Fork a child native session from friendly-cli and kill it afterwards.
	forkOut, errOut, handled, code := run("fork", "friendly-cli", "forked-child", "--detach", "--json")
	if !handled || code != 0 || !strings.Contains(forkOut, `"parent":"cli-e2e"`) || !strings.Contains(forkOut, `"backend":"native"`) {
		t.Fatalf("fork failed: handled=%v code=%d out=%q err=%q", handled, code, forkOut, errOut)
	}
	if _, errOut, handled, code = run("kill", "forked-child"); !handled || code != 0 {
		t.Fatalf("kill forked child failed: handled=%v code=%d err=%q", handled, code, errOut)
	}

	// List sessions with `--backend native` (plain and --json) without env var.
	out, errOut, handled, code = run("ls", "--backend", "native")
	if !handled || code != 0 || !strings.Contains(out, "friendly-cli") || !strings.Contains(out, "[native]") {
		t.Fatalf("ls --backend native failed: handled=%v code=%d out=%q err=%q", handled, code, out, errOut)
	}
	out, errOut, handled, code = run("ls", "--json")
	if !handled || code != 0 || !strings.Contains(out, `"cli-e2e"`) || !strings.Contains(out, `"native"`) {
		t.Fatalf("merged ls --json failed: handled=%v code=%d out=%q err=%q", handled, code, out, errOut)
	}

	// Send command and capture output using friendly label (zero env var or flags).
	_, errOut, handled, code = run("send", "friendly-cli", "echo CLI_NATIVE_OK")
	if !handled || code != 0 {
		t.Fatalf("send by label failed: handled=%v code=%d err=%q", handled, code, errOut)
	}
	deadline := time.Now().Add(4 * time.Second)
	captured := ""
	for time.Now().Before(deadline) {
		captured, _, _, _ = run("capture", "friendly-cli", "--lines", "50")
		if strings.Contains(captured, "CLI_NATIVE_OK") {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !strings.Contains(captured, "CLI_NATIVE_OK") {
		t.Fatalf("capture by label missing CLI_NATIVE_OK: %q", captured)
	}

	// Window & pane subcommands: create named window `logs`, list, select, split with --right, pane ls, then close.
	winID, errOut, handled, code := run("window", "new", "cli-e2e", "logs")
	if !handled || code != 0 || winID == "" {
		t.Fatalf("window new failed: handled=%v code=%d out=%q err=%q", handled, code, winID, errOut)
	}
	winList, errOut, handled, code := run("window", "ls", "cli-e2e")
	if !handled || code != 0 || !strings.Contains(winList, "logs") || !strings.Contains(winList, "[活跃]") {
		t.Fatalf("window ls failed: handled=%v code=%d out=%q err=%q", handled, code, winList, errOut)
	}
	_, errOut, handled, code = run("window", "select", "cli-e2e", "1")
	if !handled || code != 0 {
		t.Fatalf("window select 1 failed: handled=%v code=%d err=%q", handled, code, errOut)
	}
	splitPane, errOut, handled, code := run("pane", "split", "cli-e2e", "--right", "--window", "logs")
	if !handled || code != 0 || splitPane == "" {
		t.Fatalf("pane split --right --window logs failed: handled=%v code=%d out=%q err=%q", handled, code, splitPane, errOut)
	}
	paneList, errOut, handled, code := run("pane", "ls", "cli-e2e", "--window", "logs")
	if !handled || code != 0 || !strings.Contains(paneList, splitPane) {
		t.Fatalf("pane ls failed: handled=%v code=%d out=%q err=%q", handled, code, paneList, errOut)
	}
	_, errOut, handled, code = run("pane", "kill", "cli-e2e", splitPane)
	if !handled || code != 0 {
		t.Fatalf("pane kill failed: handled=%v code=%d err=%q", handled, code, errOut)
	}

	// Attach directly to `cli-e2e:logs` shorthand and detach via Ctrl+b d.
	inWinR, inWinW := io.Pipe()
	var winAttachOut, winAttachErr bytes.Buffer
	winDone := make(chan int, 1)
	go func() {
		_, c := dispatchNativeSessionCLI("attach", []string{"cli-e2e:logs"}, inWinR, &winAttachOut, &winAttachErr)
		winDone <- c
	}()
	time.Sleep(200 * time.Millisecond)
	_, _ = inWinW.Write([]byte{nativeattach.DefaultPrefix, 'd'})
	select {
	case c := <-winDone:
		if c != 0 {
			t.Fatalf("attach cli-e2e:logs exited with %d, err=%q", c, winAttachErr.String())
		}
	case <-time.After(4 * time.Second):
		t.Fatalf("attach cli-e2e:logs did not detach cleanly")
	}
	_ = inWinW.Close()

	_, errOut, handled, code = run("window", "kill", "cli-e2e", "logs")
	if !handled || code != 0 {
		t.Fatalf("window kill logs failed: handled=%v code=%d err=%q", handled, code, errOut)
	}

	// Legacy sp/lw/kp aliases remain backward-compatible.
	newPane, errOut, handled, code := run("sp", "cli-e2e", "-h")
	if !handled || code != 0 || newPane == "" {
		t.Fatalf("sp failed: handled=%v code=%d out=%q err=%q", handled, code, newPane, errOut)
	}
	wins, errOut, handled, code := run("lw", "cli-e2e")
	if !handled || code != 0 || !strings.Contains(wins, newPane) {
		t.Fatalf("lw failed: handled=%v code=%d out=%q err=%q", handled, code, wins, errOut)
	}
	_, errOut, handled, code = run("kp", "cli-e2e", newPane)
	if !handled || code != 0 {
		t.Fatalf("kp failed: handled=%v code=%d err=%q", handled, code, errOut)
	}

	// Attach via CLI and detach via Ctrl+b d (zero env var).
	inR, inW := io.Pipe()
	var attachOut, attachErr bytes.Buffer
	done := make(chan int, 1)
	go func() {
		_, c := dispatchNativeSessionCLI("a", []string{"cli-e2e"}, inR, &attachOut, &attachErr)
		done <- c
	}()
	time.Sleep(200 * time.Millisecond)
	_, _ = inW.Write([]byte{nativeattach.DefaultPrefix, 'd'})
	select {
	case c := <-done:
		if c != 0 {
			t.Fatalf("attach exited with %d, err=%q", c, attachErr.String())
		}
	case <-time.After(4 * time.Second):
		t.Fatalf("attach did not detach cleanly")
	}
	_ = inW.Close()
	if !strings.Contains(attachOut.String(), "CLI_NATIVE_OK") {
		t.Fatalf("attach output missing snapshot replay: %q", attachOut.String())
	}

	// Unknown session falls back cleanly to legacy tmux (handled=false).
	_, _, handled, _ = run("a", "nonexistent-tmux-only-session")
	if handled {
		t.Fatalf("unknown native session should fall back to tmux (handled=false)")
	}
}

func TestNativeTerminalEnabledDefaultAndOptOut(t *testing.T) {
	t.Setenv("ROAMI_NATIVE_TERMINAL", "")
	if !nativeTerminalEnabled() {
		t.Fatal("nativeTerminalEnabled() should default to true")
	}
	for _, off := range []string{"0", "false", "OFF", " False "} {
		t.Setenv("ROAMI_NATIVE_TERMINAL", off)
		if nativeTerminalEnabled() {
			t.Fatalf("nativeTerminalEnabled() should be false for %q", off)
		}
	}
	for _, on := range []string{"1", "true", "on"} {
		t.Setenv("ROAMI_NATIVE_TERMINAL", on)
		if !nativeTerminalEnabled() {
			t.Fatalf("nativeTerminalEnabled() should be true for %q", on)
		}
	}
}

func TestDefaultNewFallsBackToTmuxWhenSessiondMissingOnUnix(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix fallback test")
	}
	tmp := t.TempDir()
	t.Setenv("ROAMI_NATIVE_TERMINAL", "")
	t.Setenv("ROAMI_SESSIOND_BIN", "")
	t.Setenv("PATH", tmp)
	t.Setenv("ROAMI_HOME", filepath.Join(tmp, "home"))
	t.Setenv("ROAMI_DATA", filepath.Join(tmp, "data"))

	var out, errOut bytes.Buffer
	handled, code := dispatchNativeSessionCLI("new", []string{"--detach", "fallback-demo"}, bytes.NewReader(nil), &out, &errOut)
	if handled || code != 0 {
		t.Fatalf("implicit default new without roami-sessiond should fall back to tmux: handled=%v code=%d out=%q err=%q", handled, code, out.String(), errOut.String())
	}

	out.Reset()
	errOut.Reset()
	handled, code = dispatchNativeSessionCLI("new", []string{"--backend", "native", "--detach", "strict-demo"}, bytes.NewReader(nil), &out, &errOut)
	if !handled || code == 0 {
		t.Fatalf("explicit --backend native without roami-sessiond should fail fast: handled=%v code=%d out=%q err=%q", handled, code, out.String(), errOut.String())
	}
}
