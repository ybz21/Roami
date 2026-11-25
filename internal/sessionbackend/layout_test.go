package sessionbackend

import (
	"encoding/json"
	"errors"
	"math"
	"testing"
)

func TestWindowSplitCollapseAndFocus(t *testing.T) {
	w := NewSinglePaneWindow("w1", "main", "n1", "p1")
	if w.Version != 1 || w.ActivePaneID != "p1" {
		t.Fatalf("unexpected initial window: %+v", w)
	}

	// Split horizontally: p1 (left) | p2 (right).
	if err := w.Split("p1", SplitHorizontal, 0.5, "s1", "n2", "p2"); err != nil {
		t.Fatalf("horizontal split failed: %v", err)
	}
	// Split p2 vertically: p2 (top-right) / p3 (bottom-right).
	if err := w.Split("p2", SplitVertical, 0.5, "s2", "n3", "p3"); err != nil {
		t.Fatalf("vertical split failed: %v", err)
	}
	if w.Version != 3 || w.ActivePaneID != "p3" {
		t.Fatalf("unexpected version/active: v=%d active=%s", w.Version, w.ActivePaneID)
	}

	ids := w.Layout.PaneIDs()
	if len(ids) != 3 || ids[0] != "p1" || ids[1] != "p2" || ids[2] != "p3" {
		t.Fatalf("PaneIDs = %v, want [p1 p2 p3]", ids)
	}

	rects := w.ComputeRects()
	if len(rects) != 3 {
		t.Fatalf("expected 3 rects, got %d", len(rects))
	}
	assertNear(t, rects[0].W, 0.5)
	assertNear(t, rects[0].H, 1.0)
	assertNear(t, rects[1].X, 0.5)
	assertNear(t, rects[1].Y, 0.0)
	assertNear(t, rects[1].H, 0.5)
	assertNear(t, rects[2].X, 0.5)
	assertNear(t, rects[2].Y, 0.5)

	// Directional focus navigation.
	if got, ok := w.FindNeighbor("p3", FocusUp); !ok || got != "p2" {
		t.Fatalf("up from p3 = %q (%v), want p2", got, ok)
	}
	if got, ok := w.FindNeighbor("p2", FocusDown); !ok || got != "p3" {
		t.Fatalf("down from p2 = %q (%v), want p3", got, ok)
	}
	if got, ok := w.FindNeighbor("p3", FocusLeft); !ok || got != "p1" {
		t.Fatalf("left from p3 = %q (%v), want p1", got, ok)
	}
	if got, ok := w.FindNeighbor("p1", FocusRight); !ok || (got != "p2" && got != "p3") {
		t.Fatalf("right from p1 = %q (%v), want p2 or p3", got, ok)
	}

	// Resize split with version check.
	if err := w.ResizeSplit("s1", 0.4, 999); !errors.Is(err, ErrLayoutConflict) {
		t.Fatalf("expected ErrLayoutConflict, got %v", err)
	}
	if err := w.ResizeSplit("s1", 0.4, w.Version); err != nil {
		t.Fatalf("ResizeSplit failed: %v", err)
	}

	// Minimum cell guard rejects squashing below 20x6.
	if err := w.ValidateMinCells(100, 30, 20, 6); err != nil {
		t.Fatalf("100x30 should satisfy min cells: %v", err)
	}
	if err := w.ValidateMinCells(40, 30, 20, 6); !errors.Is(err, ErrPaneTooSmall) {
		t.Fatalf("40x30 with 0.4 ratio (16 cols) must fail ErrPaneTooSmall, got %v", err)
	}

	// Remove p2 -> s2 collapses to p3.
	empty, err := w.RemovePane("p2")
	if err != nil || empty {
		t.Fatalf("RemovePane(p2) empty=%v err=%v", empty, err)
	}
	if got := w.Layout.PaneIDs(); len(got) != 2 || got[0] != "p1" || got[1] != "p3" {
		t.Fatalf("after removing p2, panes = %v", got)
	}

	// Remove p3 -> root collapses to p1; active switches to p1.
	empty, err = w.RemovePane("p3")
	if err != nil || empty || w.ActivePaneID != "p1" {
		t.Fatalf("RemovePane(p3) empty=%v active=%s err=%v", empty, w.ActivePaneID, err)
	}

	// JSON round-trip.
	raw, err := json.Marshal(w)
	if err != nil {
		t.Fatal(err)
	}
	var decoded Window
	if err := json.Unmarshal(raw, &decoded); err != nil || decoded.Layout.PaneID != "p1" {
		t.Fatalf("JSON round-trip failed: err=%v decoded=%+v", err, decoded)
	}

	// Removing last pane marks window empty.
	empty, err = w.RemovePane("p1")
	if err != nil || !empty {
		t.Fatalf("RemovePane(last) empty=%v err=%v", empty, err)
	}
}

func assertNear(t *testing.T, got, want float64) {
	t.Helper()
	if math.Abs(got-want) > 1e-6 {
		t.Fatalf("got %f, want %f", got, want)
	}
}
