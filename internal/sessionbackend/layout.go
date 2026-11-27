package sessionbackend

import (
	"fmt"
	"math"
)

type NodeKind string

const (
	NodePane  NodeKind = "pane"
	NodeSplit NodeKind = "split"
)

type SplitDir string

const (
	// SplitHorizontal places First on the left and Second on the right (CSS flex-direction: row).
	SplitHorizontal SplitDir = "horizontal"
	// SplitVertical places First on top and Second on the bottom (CSS flex-direction: column).
	SplitVertical SplitDir = "vertical"
)

type FocusDir string

const (
	FocusLeft  FocusDir = "left"
	FocusRight FocusDir = "right"
	FocusUp    FocusDir = "up"
	FocusDown  FocusDir = "down"
)

const (
	MinSplitRatio = 0.1
	MaxSplitRatio = 0.9
)

// LayoutNode is a binary split tree node: either a leaf pane or a horizontal/vertical split.
type LayoutNode struct {
	ID     string      `json:"id"`
	Kind   NodeKind    `json:"kind"`
	PaneID string      `json:"paneId,omitempty"`
	Dir    SplitDir    `json:"dir,omitempty"`
	Ratio  float64     `json:"ratio,omitempty"`
	First  *LayoutNode `json:"first,omitempty"`
	Second *LayoutNode `json:"second,omitempty"`
}

// Window holds one binary split tree, its active pane, and a monotonic layout version.
type Window struct {
	ID           string      `json:"id"`
	Name         string      `json:"name,omitempty"`
	Layout       *LayoutNode `json:"layout"`
	ActivePaneID string      `json:"activePaneId"`
	Version      int64       `json:"version"`
}

// Rect is a normalized [0, 1] layout rectangle for a pane within its window.
type Rect struct {
	PaneID string  `json:"paneId"`
	X      float64 `json:"x"`
	Y      float64 `json:"y"`
	W      float64 `json:"w"`
	H      float64 `json:"h"`
}

// CellRect is a pane's exact 0-based cell rectangle inside a composited terminal viewport.
type CellRect struct {
	PaneID string
	X, Y   int
	W, H   int
}

// CellDivider is a 1-cell box-drawing divider between split panes.
type CellDivider struct {
	Horizontal bool
	X, Y, Len  int
}

// CellLayout holds the exact pane cell rectangles and dividers for a viewport grid.
type CellLayout struct {
	Panes    []CellRect
	Dividers []CellDivider
}

// ComputeCellLayout turns a binary LayoutNode tree into exact non-overlapping cell rectangles
// separated by 1-cell dividers (│ for horizontal splits, ─ for vertical splits).
func ComputeCellLayout(root *LayoutNode, cols, rows int) CellLayout {
	var out CellLayout
	if root == nil || cols < 1 || rows < 1 {
		return out
	}
	layoutNodeCells(root, 0, 0, cols, rows, &out)
	return out
}

func layoutNodeCells(n *LayoutNode, x, y, w, h int, out *CellLayout) {
	if n == nil || w < 1 || h < 1 {
		return
	}
	if n.Kind == NodePane {
		out.Panes = append(out.Panes, CellRect{PaneID: n.PaneID, X: x, Y: y, W: w, H: h})
		return
	}
	ratio := clampRatio(n.Ratio)
	if n.Dir == SplitHorizontal {
		if w >= 3 {
			leftW := int(math.Round(float64(w-1) * ratio))
			if leftW < 1 {
				leftW = 1
			}
			if leftW > w-2 {
				leftW = w - 2
			}
			out.Dividers = append(out.Dividers, CellDivider{Horizontal: false, X: x + leftW, Y: y, Len: h})
			layoutNodeCells(n.First, x, y, leftW, h, out)
			layoutNodeCells(n.Second, x+leftW+1, y, w-leftW-1, h, out)
			return
		}
		leftW := w / 2
		if leftW < 1 {
			leftW = 1
		}
		layoutNodeCells(n.First, x, y, leftW, h, out)
		if w-leftW > 0 {
			layoutNodeCells(n.Second, x+leftW, y, w-leftW, h, out)
		}
		return
	}

	if h >= 3 {
		topH := int(math.Round(float64(h-1) * ratio))
		if topH < 1 {
			topH = 1
		}
		if topH > h-2 {
			topH = h - 2
		}
		out.Dividers = append(out.Dividers, CellDivider{Horizontal: true, X: x, Y: y + topH, Len: w})
		layoutNodeCells(n.First, x, y, w, topH, out)
		layoutNodeCells(n.Second, x, y+topH+1, w, h-topH-1, out)
		return
	}
	topH := h / 2
	if topH < 1 {
		topH = 1
	}
	layoutNodeCells(n.First, x, y, w, topH, out)
	if h-topH > 0 {
		layoutNodeCells(n.Second, x, y+topH, w, h-topH, out)
	}
}

// NewSinglePaneWindow constructs the default single-pane window (a 1-leaf tree).
func NewSinglePaneWindow(windowID, name, nodeID, paneID string) Window {
	return Window{
		ID:           windowID,
		Name:         name,
		ActivePaneID: paneID,
		Version:      1,
		Layout: &LayoutNode{
			ID:     nodeID,
			Kind:   NodePane,
			PaneID: paneID,
		},
	}
}

// Clone returns a deep copy of the layout tree.
func (n *LayoutNode) Clone() *LayoutNode {
	if n == nil {
		return nil
	}
	cp := *n
	cp.First = n.First.Clone()
	cp.Second = n.Second.Clone()
	return &cp
}

// Clone returns a deep copy of the window.
func (w Window) Clone() Window {
	w.Layout = w.Layout.Clone()
	return w
}

// PaneIDs returns all pane IDs in left-to-right / top-to-bottom DFS order.
func (n *LayoutNode) PaneIDs() []string {
	if n == nil {
		return nil
	}
	if n.Kind == NodePane {
		return []string{n.PaneID}
	}
	out := n.First.PaneIDs()
	return append(out, n.Second.PaneIDs()...)
}

// ContainsPane reports whether paneID exists in this tree.
func (n *LayoutNode) ContainsPane(paneID string) bool {
	if n == nil {
		return false
	}
	if n.Kind == NodePane {
		return n.PaneID == paneID
	}
	return n.First.ContainsPane(paneID) || n.Second.ContainsPane(paneID)
}

func clampRatio(ratio float64) float64 {
	if ratio == 0 || math.IsNaN(ratio) || math.IsInf(ratio, 0) {
		return 0.5
	}
	if ratio < MinSplitRatio {
		return MinSplitRatio
	}
	if ratio > MaxSplitRatio {
		return MaxSplitRatio
	}
	return ratio
}

// Split replaces targetPaneID in place with a split node containing the original pane and newPaneID.
func (w *Window) Split(targetPaneID string, dir SplitDir, ratio float64, splitNodeID, newLeafNodeID, newPaneID string) error {
	if dir != SplitHorizontal && dir != SplitVertical {
		return fmt.Errorf("invalid split direction %q", dir)
	}
	if w.Layout == nil {
		return ErrPaneNotFound
	}
	ratio = clampRatio(ratio)
	replaced := splitNode(w.Layout, targetPaneID, dir, ratio, splitNodeID, newLeafNodeID, newPaneID)
	if !replaced {
		return ErrPaneNotFound
	}
	w.ActivePaneID = newPaneID
	w.Version++
	return nil
}

func splitNode(n *LayoutNode, targetPaneID string, dir SplitDir, ratio float64, splitNodeID, newLeafNodeID, newPaneID string) bool {
	if n == nil {
		return false
	}
	if n.Kind == NodePane {
		if n.PaneID != targetPaneID {
			return false
		}
		orig := &LayoutNode{ID: n.ID, Kind: NodePane, PaneID: n.PaneID}
		added := &LayoutNode{ID: newLeafNodeID, Kind: NodePane, PaneID: newPaneID}
		n.ID = splitNodeID
		n.Kind = NodeSplit
		n.PaneID = ""
		n.Dir = dir
		n.Ratio = ratio
		n.First = orig
		n.Second = added
		return true
	}
	return splitNode(n.First, targetPaneID, dir, ratio, splitNodeID, newLeafNodeID, newPaneID) ||
		splitNode(n.Second, targetPaneID, dir, ratio, splitNodeID, newLeafNodeID, newPaneID)
}

// RemovePane removes paneID and collapses its parent split so no empty slot remains.
// Returns windowEmpty=true when the last pane in the window was removed.
func (w *Window) RemovePane(paneID string) (windowEmpty bool, err error) {
	if w.Layout == nil {
		return true, ErrPaneNotFound
	}
	next, removed := removePaneNode(w.Layout, paneID)
	if !removed {
		return false, ErrPaneNotFound
	}
	w.Layout = next
	w.Version++
	if next == nil {
		w.ActivePaneID = ""
		return true, nil
	}
	if w.ActivePaneID == paneID || !w.Layout.ContainsPane(w.ActivePaneID) {
		ids := w.Layout.PaneIDs()
		if len(ids) > 0 {
			w.ActivePaneID = ids[0]
		}
	}
	return false, nil
}

func removePaneNode(n *LayoutNode, paneID string) (*LayoutNode, bool) {
	if n == nil {
		return nil, false
	}
	if n.Kind == NodePane {
		if n.PaneID == paneID {
			return nil, true
		}
		return n, false
	}
	if n.First != nil && n.First.Kind == NodePane && n.First.PaneID == paneID {
		return n.Second, true
	}
	if n.Second != nil && n.Second.Kind == NodePane && n.Second.PaneID == paneID {
		return n.First, true
	}
	if nextFirst, ok := removePaneNode(n.First, paneID); ok {
		n.First = nextFirst
		return n, true
	}
	if nextSecond, ok := removePaneNode(n.Second, paneID); ok {
		n.Second = nextSecond
		return n, true
	}
	return n, false
}

// ResizeSplit updates a split node's ratio, rejecting stale layout versions when expectedVersion > 0.
func (w *Window) ResizeSplit(nodeID string, ratio float64, expectedVersion int64) error {
	if expectedVersion > 0 && w.Version != expectedVersion {
		return ErrLayoutConflict
	}
	if !resizeSplitNode(w.Layout, nodeID, clampRatio(ratio)) {
		return fmt.Errorf("split node not found: %s", nodeID)
	}
	w.Version++
	return nil
}

func resizeSplitNode(n *LayoutNode, nodeID string, ratio float64) bool {
	if n == nil || n.Kind != NodeSplit {
		return false
	}
	if n.ID == nodeID {
		n.Ratio = ratio
		return true
	}
	return resizeSplitNode(n.First, nodeID, ratio) || resizeSplitNode(n.Second, nodeID, ratio)
}

// ComputeRects calculates each pane's normalized [0, 1] bounding box.
func (w Window) ComputeRects() []Rect {
	var rects []Rect
	computeRectsNode(w.Layout, 0, 0, 1, 1, &rects)
	return rects
}

func computeRectsNode(n *LayoutNode, x, y, width, height float64, out *[]Rect) {
	if n == nil {
		return
	}
	if n.Kind == NodePane {
		*out = append(*out, Rect{PaneID: n.PaneID, X: x, Y: y, W: width, H: height})
		return
	}
	r := clampRatio(n.Ratio)
	if n.Dir == SplitHorizontal {
		w1 := width * r
		computeRectsNode(n.First, x, y, w1, height, out)
		computeRectsNode(n.Second, x+w1, y, width-w1, height, out)
		return
	}
	h1 := height * r
	computeRectsNode(n.First, x, y, width, h1, out)
	computeRectsNode(n.Second, x, y+h1, width, height-h1, out)
}

// ValidateMinCells ensures every pane fits at least minCols x minRows within a total cell budget.
func (w Window) ValidateMinCells(totalCols, totalRows, minCols, minRows uint16) error {
	for _, r := range w.ComputeRects() {
		cols := uint16(math.Floor(r.W * float64(totalCols)))
		rows := uint16(math.Floor(r.H * float64(totalRows)))
		if cols < minCols || rows < minRows {
			return fmt.Errorf("%w: pane %s would be %dx%d (min %dx%d)", ErrPaneTooSmall, r.PaneID, cols, rows, minCols, minRows)
		}
	}
	return nil
}

// FindNeighbor picks the closest adjacent pane in the requested cardinal direction.
func (w Window) FindNeighbor(paneID string, dir FocusDir) (string, bool) {
	rects := w.ComputeRects()
	var src Rect
	found := false
	for _, r := range rects {
		if r.PaneID == paneID {
			src = r
			found = true
			break
		}
	}
	if !found {
		return "", false
	}
	const eps = 1e-6
	bestID := ""
	bestDist := math.MaxFloat64
	srcCX, srcCY := src.X+src.W/2, src.Y+src.H/2
	for _, c := range rects {
		if c.PaneID == paneID {
			continue
		}
		var aligned bool
		var gap float64
		switch dir {
		case FocusRight:
			aligned = overlap(src.Y, src.Y+src.H, c.Y, c.Y+c.H) > eps && c.X >= src.X+src.W-eps
			gap = c.X - (src.X + src.W)
		case FocusLeft:
			aligned = overlap(src.Y, src.Y+src.H, c.Y, c.Y+c.H) > eps && c.X+c.W <= src.X+eps
			gap = src.X - (c.X + c.W)
		case FocusDown:
			aligned = overlap(src.X, src.X+src.W, c.X, c.X+c.W) > eps && c.Y >= src.Y+src.H-eps
			gap = c.Y - (src.Y + src.H)
		case FocusUp:
			aligned = overlap(src.X, src.X+src.W, c.X, c.X+c.W) > eps && c.Y+c.H <= src.Y+eps
			gap = src.Y - (c.Y + c.H)
		}
		if !aligned {
			continue
		}
		if gap < 0 {
			gap = 0
		}
		cx, cy := c.X+c.W/2, c.Y+c.H/2
		// Prefer directly adjacent edges, breaking ties by center proximity.
		score := gap*100 + math.Hypot(cx-srcCX, cy-srcCY)
		if score < bestDist {
			bestDist = score
			bestID = c.PaneID
		}
	}
	return bestID, bestID != ""
}

func overlap(a1, a2, b1, b2 float64) float64 {
	start := math.Max(a1, b1)
	end := math.Min(a2, b2)
	if end <= start {
		return 0
	}
	return end - start
}
