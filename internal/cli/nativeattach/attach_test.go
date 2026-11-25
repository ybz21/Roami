package nativeattach

import (
	"bytes"
	"context"
	"io"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionhost"
)

func TestPrefixFilterChords(t *testing.T) {
	f := NewPrefixFilter(DefaultPrefix)

	// Split Ctrl+b and 'd' across two chunks.
	if acts := f.Feed([]byte{'a', DefaultPrefix}); len(acts) != 1 || acts[0].Kind != ActionForward || string(acts[0].Data) != "a" {
		t.Fatalf("unexpected chunk 1 actions: %+v", acts)
	}
	if acts := f.Feed([]byte{'d'}); len(acts) != 1 || acts[0].Kind != ActionDetach {
		t.Fatalf("expected ActionDetach, got %+v", acts)
	}

	// Double Ctrl+b forwards literal 0x02; unknown chord forwards both bytes; window/menu/pane chords trigger actions.
	acts := f.Feed([]byte{
		DefaultPrefix, DefaultPrefix,
		DefaultPrefix, 'z',
		DefaultPrefix, '%',
		DefaultPrefix, '"',
		DefaultPrefix, 'o',
		DefaultPrefix, 'x',
		DefaultPrefix, 'c',
		DefaultPrefix, 'n',
		DefaultPrefix, 'p',
		DefaultPrefix, '2',
		DefaultPrefix, '&',
		DefaultPrefix, 'm',
		DefaultPrefix, 'w',
	})
	wantKinds := []ActionKind{
		ActionForward, ActionSplitH, ActionSplitV, ActionNextPane, ActionClosePane,
		ActionNewWindow, ActionNextWindow, ActionPrevWindow, ActionSelectWindow,
		ActionCloseWindow, ActionOpenMenu, ActionOpenWindowSwitcher,
	}
	if len(acts) != len(wantKinds) {
		t.Fatalf("got %d actions %+v, want %d", len(acts), acts, len(wantKinds))
	}
	for i, want := range wantKinds {
		if acts[i].Kind != want {
			t.Fatalf("action[%d] = %v, want %v", i, acts[i].Kind, want)
		}
	}
	if acts[8].Index != 2 {
		t.Fatalf("ActionSelectWindow index = %d, want 2", acts[8].Index)
	}
	if !bytes.Equal(acts[0].Data, []byte{DefaultPrefix, DefaultPrefix, 'z'}) {
		t.Fatalf("forwarded bytes = %v, want [%d %d 'z']", acts[0].Data, DefaultPrefix, DefaultPrefix)
	}
}

func TestStatusBarFormattingAndWidthClipping(t *testing.T) {
	info := statusBarInfo{
		SessionLabel: "dev",
		Windows: []sessionbackend.Window{
			sessionbackend.NewSinglePaneWindow("w-1", "main", "n-1", "p-1"),
			sessionbackend.NewSinglePaneWindow("w-2", "logs", "n-2", "p-2"),
		},
		ActiveWindowID: "w-2",
		ActivePaneID:   "p-2",
	}
	wide := formatStatusBarText(info, 120)
	if !strings.Contains(wide, "[dev]") || !strings.Contains(wide, "1:main") || !strings.Contains(wide, "2:logs*") || !strings.Contains(wide, "Ctrl+b m:菜单") {
		t.Fatalf("unexpected wide status bar: %q", wide)
	}
	if gotW := displayWidth(wide); gotW != 120 {
		t.Fatalf("wide status bar displayWidth = %d, want 120", gotW)
	}

	narrow := formatStatusBarText(info, 36)
	if gotW := displayWidth(narrow); gotW > 36 {
		t.Fatalf("narrow status bar overflowed: width=%d > 36 (%q)", gotW, narrow)
	}

	info.PrefixPending = true
	pending := formatStatusBarText(info, 100)
	if !strings.Contains(pending, "[Ctrl+b]") || displayWidth(pending) != 100 {
		t.Fatalf("unexpected pending status bar: width=%d text=%q", displayWidth(pending), pending)
	}
}

func TestAttachMenuAndWindowSwitcher(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix shell integration test")
	}
	host := sessionhost.NewHost(sessionhost.Config{
		HostID:  "cli-menu-test",
		LogsDir: t.TempDir(),
	})
	defer host.Shutdown(context.Background())

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	ref, err := host.Create(ctx, sessionbackend.CreateSpec{
		SessionID: "menu-demo",
		Exe:       "/bin/sh",
		Cols:      80,
		Rows:      24,
	})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}
	win2, err := host.NewWindow(ctx, ref.SessionID, sessionbackend.WindowSpec{
		Name: "logs",
		Exe:  "/bin/sh",
		Cols: 80,
		Rows: 24,
	})
	if err != nil {
		t.Fatalf("NewWindow: %v", err)
	}

	// Attach directly into window 1 (ref.WindowID), enable status bar explicitly, then exercise
	// Ctrl+b m (command menu -> 'w' window switcher -> '2' jump to logs) and Ctrl+b % split inside logs.
	showBar := true
	inR, inW := io.Pipe()
	out := &syncBuffer{}
	done := make(chan error, 1)
	go func() {
		done <- Attach(ctx, host, host, AttachOptions{
			SessionID:     ref.SessionID,
			WindowID:      ref.WindowID,
			In:            inR,
			Out:           out,
			ShowStatusBar: &showBar,
			Cols:          100,
			Rows:          24,
		})
	}()

	waitFor(t, 4*time.Second, func() bool {
		return strings.Contains(out.String(), "Ctrl+b m:菜单") && strings.Contains(out.String(), "2:logs")
	}, "bottom status bar rendered")

	// Open interactive command menu (Ctrl+b m), verify menu appears, then press 'w' for window switcher, then '2' to enter logs.
	_, _ = inW.Write([]byte{DefaultPrefix, 'm'})
	waitFor(t, 3*time.Second, func() bool {
		return strings.Contains(out.String(), "Roami 终端菜单")
	}, "interactive command menu")

	_, _ = inW.Write([]byte{'w'})
	waitFor(t, 3*time.Second, func() bool {
		return strings.Contains(out.String(), "切换窗口 / 窗格")
	}, "window switcher overlay")

	_, _ = inW.Write([]byte{'2'})
	waitFor(t, 4*time.Second, func() bool {
		cur, err := host.Observe(ctx, ref.SessionID)
		return err == nil && cur.ActiveWindowID == win2.ID
	}, "window switcher jumped to window 2")

	// Split inside window 2 using Ctrl+b % and confirm window 2 now has 2 panes.
	_, _ = inW.Write([]byte{DefaultPrefix, '%'})
	waitFor(t, 4*time.Second, func() bool {
		cur, err := host.Observe(ctx, ref.SessionID)
		if err != nil || len(cur.Windows) < 2 || cur.Windows[1].Layout == nil {
			return false
		}
		return len(cur.Windows[1].Layout.PaneIDs()) == 2
	}, "split inside window 2")

	_, _ = inW.Write([]byte{DefaultPrefix, 'd'})
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Attach returned error: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatalf("Attach did not detach cleanly")
	}
	_ = inW.Close()
}

func TestFilterAutoReplies(t *testing.T) {
	in := []byte("hi\x1b[?62;4c\x1b[12;34R\x1b[>0;276;0c\x1b[Aok")
	got := FilterAutoReplies(in)
	want := []byte("hi\x1b[Aok")
	if !bytes.Equal(got, want) {
		t.Fatalf("FilterAutoReplies = %q, want %q", got, want)
	}
}

type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

func TestAttachDetachAndReattachPreservesSession(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix shell integration test")
	}
	host := sessionhost.NewHost(sessionhost.Config{
		HostID:  "cli-attach-test",
		LogsDir: t.TempDir(),
	})
	defer host.Shutdown(context.Background())

	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	ref, err := host.Create(ctx, sessionbackend.CreateSpec{
		SessionID: "dev-cli",
		Exe:       "/bin/sh",
		Cols:      80,
		Rows:      24,
	})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	// First attach: run a command, observe output, then detach with Ctrl+b d.
	inR, inW := io.Pipe()
	out := &syncBuffer{}
	done := make(chan error, 1)
	go func() {
		done <- Attach(ctx, host, host, AttachOptions{
			SessionID: ref.SessionID,
			In:        inR,
			Out:       out,
			Cols:      80,
			Rows:      24,
		})
	}()

	time.Sleep(150 * time.Millisecond)
	_, _ = inW.Write([]byte("echo HELLO_TMUX_STYLE_ATTACH\n"))

	waitFor(t, 4*time.Second, func() bool {
		return strings.Contains(out.String(), "HELLO_TMUX_STYLE_ATTACH")
	}, "first attach output")

	// Detach with Ctrl+b d.
	_, _ = inW.Write([]byte{DefaultPrefix, 'd'})
	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("first Attach returned error: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatalf("Attach did not detach on Ctrl+b d")
	}
	_ = inW.Close()

	// Session must still be alive after detach.
	st, err := host.Observe(ctx, ref.SessionID)
	if err != nil || st.Status != sessionbackend.StatusAlive {
		t.Fatalf("session should stay alive after detach, got state=%+v err=%v", st, err)
	}

	// Re-attach and verify snapshot immediately replays previous output.
	inR2, inW2 := io.Pipe()
	out2 := &syncBuffer{}
	done2 := make(chan error, 1)
	go func() {
		done2 <- Attach(ctx, host, host, AttachOptions{
			SessionID: ref.SessionID,
			In:        inR2,
			Out:       out2,
			Cols:      80,
			Rows:      24,
		})
	}()

	waitFor(t, 4*time.Second, func() bool {
		return strings.Contains(out2.String(), "HELLO_TMUX_STYLE_ATTACH")
	}, "re-attach snapshot replay")

	// Split horizontally via Ctrl+b % and verify a second pane is created.
	_, _ = inW2.Write([]byte{DefaultPrefix, '%'})
	waitFor(t, 4*time.Second, func() bool {
		cur, err := host.Observe(ctx, ref.SessionID)
		return err == nil && len(cur.Windows) == 1 && cur.Windows[0].Layout != nil && len(cur.Windows[0].Layout.PaneIDs()) == 2
	}, "Ctrl+b % split pane")

	_, _ = inW2.Write([]byte{DefaultPrefix, 'd'})
	select {
	case err := <-done2:
		if err != nil {
			t.Fatalf("second Attach returned error: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatalf("second Attach did not detach on Ctrl+b d")
	}
	_ = inW2.Close()
}

func waitFor(t *testing.T, timeout time.Duration, pred func() bool, desc string) {
	t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if pred() {
			return
		}
		time.Sleep(30 * time.Millisecond)
	}
	t.Fatalf("timed out waiting for %s", desc)
}
