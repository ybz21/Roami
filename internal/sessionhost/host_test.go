package sessionhost

import (
	"context"
	"errors"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
)

func TestCoordDBAtomicSwitchIdempotencyAndDrainCap(t *testing.T) {
	db, err := OpenCoordDB(filepath.Join(t.TempDir(), "session-host.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()

	for _, id := range []string{"h1", "h2", "h3", "h4"} {
		if err := db.RegisterHost(HostRecord{HostID: id, Version: "1.0", Endpoint: "/tmp/" + id + ".sock"}); err != nil {
			t.Fatal(err)
		}
	}

	// Concurrent initial switch: exactly one wins CAS from generation 0 -> 1.
	var wg sync.WaitGroup
	wins := make(chan string, 2)
	for _, target := range []string{"h1", "h2"} {
		wg.Add(1)
		go func(tid string) {
			defer wg.Done()
			if _, err := db.SwitchHost(tid, "", 0, 2); err == nil {
				wins <- tid
			}
		}(target)
	}
	wg.Wait()
	close(wins)
	var winner string
	count := 0
	for w := range wins {
		winner = w
		count++
	}
	if count != 1 {
		t.Fatalf("expected exactly 1 CAS winner, got %d", count)
	}

	ptr, err := db.Pointer()
	if err != nil || ptr.CurrentHost != winner || ptr.Generation != 1 {
		t.Fatalf("unexpected pointer: %+v err=%v", ptr, err)
	}

	// Idempotent admission & stale generation rejection.
	op, existed, err := db.AdmitCreate("op-1", "digest-a", winner, 1)
	if err != nil || existed || op.State != OpStateAccepted {
		t.Fatalf("AdmitCreate = %+v existed=%v err=%v", op, existed, err)
	}
	// Duplicate with same digest returns existing record.
	op2, existed, err := db.AdmitCreate("op-1", "digest-a", winner, 1)
	if err != nil || !existed || op2.OperationID != "op-1" {
		t.Fatalf("duplicate AdmitCreate failed: %+v existed=%v err=%v", op2, existed, err)
	}
	// Duplicate with conflicting digest is rejected.
	if _, _, err := db.AdmitCreate("op-1", "digest-other", winner, 1); !errors.Is(err, ErrOperationConflict) {
		t.Fatalf("expected ErrOperationConflict, got %v", err)
	}
	// Only one worker can claim start.
	c1, _ := db.ClaimStart("op-1", winner)
	c2, _ := db.ClaimStart("op-1", winner)
	if !c1 || c2 {
		t.Fatalf("ClaimStart must succeed exactly once: c1=%v c2=%v", c1, c2)
	}

	// Switch to h3 (1 draining: winner) and h4 (2 draining: winner, h3).
	next := "h2"
	if winner == "h2" {
		next = "h1"
	}
	if _, err := db.SwitchHost("h3", winner, 1, 2); err != nil {
		t.Fatalf("switch to h3 failed: %v", err)
	}
	// Stale host must reject new operation.
	if _, _, err := db.AdmitCreate("op-stale", "d", winner, 1); !errors.Is(err, sessionbackend.ErrStaleGeneration) {
		t.Fatalf("expected ErrStaleGeneration, got %v", err)
	}
	if _, err := db.SwitchHost("h4", "h3", 2, 2); err != nil {
		t.Fatalf("switch to h4 failed: %v", err)
	}
	// Now 2 hosts are draining (winner, h3) -> switching to a fresh host must hit ErrDrainingCap!
	if _, err := db.SwitchHost(next, "h4", 3, 2); !errors.Is(err, sessionbackend.ErrDrainingCap) {
		t.Fatalf("expected ErrDrainingCap with 2 draining hosts, got %v", err)
	}

	// Rollback to h3 succeeds and increments generation to 4 (h3 stops draining, h4 starts draining).
	ptr, err = db.SwitchHost("h3", "h4", 3, 2)
	if err != nil || ptr.CurrentHost != "h3" || ptr.Generation != 4 {
		t.Fatalf("rollback failed: ptr=%+v err=%v", ptr, err)
	}
}

func TestEmulatorQueriesScrollbackAndLastRealCol(t *testing.T) {
	em := NewEmulator(40, 4, 100)
	// Overflow 4-row screen into scrollback.
	em.Feed([]byte("line1\r\nline2\r\nline3\r\nline4\r\nline5\r\nline6"))
	if txt := em.CaptureText(10, true); !strings.Contains(txt, "line1") || !strings.Contains(txt, "line6") {
		t.Fatalf("scrollback missing: %q", txt)
	}

	// DSR cursor query (ESC[6n) and DA1 (ESC[c) get immediate server replies.
	em.Feed([]byte("\x1b[2;5H"))
	replies, _ := em.Feed([]byte("\x1b[6n\x1b[c"))
	if len(replies) != 2 || string(replies[0]) != "\x1b[2;5R" || string(replies[1]) != "\x1b[?62;c" {
		t.Fatalf("unexpected VT replies: %q", replies)
	}

	// Dim/gray ghost suggestion ignored by LastRealCol.
	em.Feed([]byte("\x1b[?1049h\x1b[1;1Hhello \x1b[90msuggestion\x1b[0m"))
	if !em.Mode().AltScreen {
		t.Fatal("expected AltScreen=true")
	}
	if last := em.LastRealCol(0); last != 4 {
		t.Fatalf("LastRealCol = %d, want 4 ('o' of 'hello')", last)
	}

	// OSC 7 cwd tracking.
	em.Feed([]byte("\x1b]7;file://localhost/tmp/project\x07"))
	if em.Cwd() != "/tmp/project" {
		t.Fatalf("Cwd = %q, want /tmp/project", em.Cwd())
	}

	// Snapshot restores into a fresh emulator cleanly.
	snap := em.SnapshotANSI()
	em2 := NewEmulator(40, 4, 100)
	em2.Feed(snap)
	if !em2.Mode().AltScreen || !strings.Contains(em2.CaptureText(10, false), "hello") {
		t.Fatalf("snapshot replay mismatch: alt=%v text=%q", em2.Mode().AltScreen, em2.CaptureText(10, false))
	}
}

func TestHostSessionLifecycleReconnectAndSplits(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()

	logsDir := t.TempDir()
	coord, err := OpenCoordDB(filepath.Join(t.TempDir(), "session-host.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer coord.Close()

	h := NewHost(Config{HostID: "h-test", LogsDir: logsDir, Coord: coord})
	defer h.Shutdown(ctx)

	if err := coord.RegisterHost(HostRecord{HostID: "h-test", State: HostStateReady}); err != nil {
		t.Fatal(err)
	}
	if _, err := coord.SwitchHost("h-test", "", 0, 2); err != nil {
		t.Fatal(err)
	}

	ref, err := h.Create(ctx, sessionbackend.CreateSpec{
		OperationID:        "create-1",
		ExpectedGeneration: 1,
		Label:              "demo",
		Exe:                "/bin/sh",
		Env:                []string{"ROAMI_NATIVE_OK=yes"},
		Cols:               80,
		Rows:               24,
	})
	if err != nil {
		t.Fatalf("Create failed: %v", err)
	}
	// Idempotent replay with same operation ID returns same session without spawning a second PTY.
	refDup, err := h.Create(ctx, sessionbackend.CreateSpec{
		OperationID:        "create-1",
		ExpectedGeneration: 1,
		Label:              "demo",
		Exe:                "/bin/sh",
		Env:                []string{"ROAMI_NATIVE_OK=yes"},
		Cols:               80,
		Rows:               24,
	})
	if err != nil || !refDup.Reused || refDup.SessionID != ref.SessionID {
		t.Fatalf("idempotent Create failed: refDup=%+v err=%v", refDup, err)
	}

	target := sessionbackend.Target{SessionID: ref.SessionID, PaneID: ref.PaneID}
	stream1, err := h.Attach(ctx, target, sessionbackend.AttachOpts{ClientID: "web-1"})
	if err != nil {
		t.Fatal(err)
	}

	// First event must be a snapshot.
	ev := <-stream1.Events()
	if ev.Kind != sessionbackend.EventSnapshot {
		t.Fatalf("first event = %s, want snapshot", ev.Kind)
	}

	lease, err := h.ClaimControl(ctx, target, "web-1")
	if err != nil {
		t.Fatal(err)
	}
	// Stale control generation must be rejected.
	if err := h.WriteInput(ctx, target, lease.ControlGen+99, []byte("bad\n")); !errors.Is(err, sessionbackend.ErrStaleControl) {
		t.Fatalf("expected ErrStaleControl, got %v", err)
	}

	// Managed idempotent submit.
	rec1, err := h.Submit(ctx, target, sessionbackend.SubmitReq{
		RequestID:   "req-1",
		Payload:     "echo HELLO_$ROAMI_NATIVE_OK",
		SubmitEnter: true,
	})
	if err != nil || !rec1.Accepted || rec1.Duplicate {
		t.Fatalf("Submit failed: %+v err=%v", rec1, err)
	}
	rec2, err := h.Submit(ctx, target, sessionbackend.SubmitReq{
		RequestID:   "req-1",
		Payload:     "echo HELLO_$ROAMI_NATIVE_OK",
		SubmitEnter: true,
	})
	if err != nil || !rec2.Duplicate {
		t.Fatalf("duplicate Submit should be deduplicated: %+v err=%v", rec2, err)
	}

	// Wait for output to appear in Capture.
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		capRes, err := h.Capture(ctx, target, sessionbackend.CaptureOpts{Lines: 50, IncludeHistory: true})
		if err == nil && strings.Contains(capRes.Text, "HELLO_yes") {
			break
		}
		time.Sleep(30 * time.Millisecond)
	}
	capRes, _ := h.Capture(ctx, target, sessionbackend.CaptureOpts{Lines: 50, IncludeHistory: true})
	if !strings.Contains(capRes.Text, "HELLO_yes") {
		t.Fatalf("expected HELLO_yes in capture, got:\n%s", capRes.Text)
	}

	// Detach stream1 -> process stays alive, control is released.
	_ = stream1.Close()
	st, err := h.Observe(ctx, ref.SessionID)
	if err != nil || st.Status != sessionbackend.StatusAlive || st.Attached != 0 {
		t.Fatalf("after detach, Observe = %+v err=%v", st, err)
	}

	// Split horizontally and vertically -> layout_changed broadcast + 3 live panes!
	winAfterH, pane2, err := h.SplitPane(ctx, ref.SessionID, ref.PaneID, sessionbackend.SplitSpec{
		Dir: sessionbackend.SplitHorizontal, Ratio: 0.5, Exe: "/bin/sh",
	})
	if err != nil || len(winAfterH.Layout.PaneIDs()) != 2 {
		t.Fatalf("horizontal SplitPane failed: win=%+v err=%v", winAfterH, err)
	}
	winAfterV, pane3, err := h.SplitPane(ctx, ref.SessionID, pane2, sessionbackend.SplitSpec{
		Dir: sessionbackend.SplitVertical, Ratio: 0.5, Exe: "/bin/sh",
	})
	if err != nil || len(winAfterV.Layout.PaneIDs()) != 3 {
		t.Fatalf("vertical SplitPane failed: win=%+v err=%v", winAfterV, err)
	}
	if h.ActivePaneCount() != 3 {
		t.Fatalf("ActivePaneCount = %d, want 3", h.ActivePaneCount())
	}

	// Close pane2 -> collapses cleanly to 2 panes.
	updated, err := h.ClosePane(ctx, ref.SessionID, pane2)
	if err != nil || updated == nil || len(updated.Layout.PaneIDs()) != 2 {
		t.Fatalf("ClosePane(pane2) failed: updated=%+v err=%v", updated, err)
	}

	// Close session terminates remaining panes.
	if err := h.Close(ctx, ref.SessionID); err != nil {
		t.Fatalf("Close session failed: %v", err)
	}
	if pane3 == "" || h.ActivePaneCount() != 0 {
		t.Fatalf("expected 0 active panes after Close, got %d", h.ActivePaneCount())
	}
}
