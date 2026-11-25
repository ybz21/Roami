package nativeattach

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"math"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionhost"
)

// paneRect is a pane's exact 0-based cell rectangle inside the composited window viewport.
type paneRect struct {
	PaneID string
	X, Y   int
	W, H   int
}

type dividerSegment struct {
	Horizontal bool
	X, Y, Len  int
}

type cellLayout struct {
	Panes    []paneRect
	Dividers []dividerSegment
}

// computeCellLayout turns a binary LayoutNode tree into exact non-overlapping cell rectangles
// separated by 1-cell box-drawing dividers (│ for horizontal splits, ─ for vertical splits).
func computeCellLayout(root *sessionbackend.LayoutNode, cols, rows int) cellLayout {
	var out cellLayout
	if root == nil || cols < 1 || rows < 1 {
		return out
	}
	layoutNodeCells(root, 0, 0, cols, rows, &out)
	return out
}

func layoutNodeCells(n *sessionbackend.LayoutNode, x, y, w, h int, out *cellLayout) {
	if n == nil || w < 1 || h < 1 {
		return
	}
	if n.Kind == sessionbackend.NodePane {
		out.Panes = append(out.Panes, paneRect{PaneID: n.PaneID, X: x, Y: y, W: w, H: h})
		return
	}
	ratio := n.Ratio
	if ratio <= 0 || math.IsNaN(ratio) || math.IsInf(ratio, 0) {
		ratio = 0.5
	}
	if ratio < sessionbackend.MinSplitRatio {
		ratio = sessionbackend.MinSplitRatio
	}
	if ratio > sessionbackend.MaxSplitRatio {
		ratio = sessionbackend.MaxSplitRatio
	}

	if n.Dir == sessionbackend.SplitHorizontal {
		if w >= 3 {
			leftW := int(math.Round(float64(w-1) * ratio))
			if leftW < 1 {
				leftW = 1
			}
			if leftW > w-2 {
				leftW = w - 2
			}
			out.Dividers = append(out.Dividers, dividerSegment{Horizontal: false, X: x + leftW, Y: y, Len: h})
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

	// SplitVertical: top / bottom.
	if h >= 3 {
		topH := int(math.Round(float64(h-1) * ratio))
		if topH < 1 {
			topH = 1
		}
		if topH > h-2 {
			topH = h - 2
		}
		out.Dividers = append(out.Dividers, dividerSegment{Horizontal: true, X: x, Y: y + topH, Len: w})
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

type borderMask uint8

const (
	maskUp borderMask = 1 << iota
	maskDown
	maskLeft
	maskRight
)

func borderGlyph(m borderMask) rune {
	switch m {
	case maskUp | maskDown | maskLeft | maskRight:
		return '┼'
	case maskDown | maskLeft | maskRight:
		return '┬'
	case maskUp | maskLeft | maskRight:
		return '┴'
	case maskUp | maskDown | maskRight:
		return '├'
	case maskUp | maskDown | maskLeft:
		return '┤'
	case maskLeft | maskRight, maskLeft, maskRight:
		return '─'
	case maskUp | maskDown, maskUp, maskDown:
		return '│'
	default:
		return '│'
	}
}

// renderCompositeFrame renders all panes in layout plus box-drawing dividers and status bar into one ANSI frame.
func renderCompositeFrame(
	layout cellLayout,
	emus map[string]*sessionhost.Emulator,
	activePaneID string,
	statusSeq []byte,
	cols, paneRows int,
) []byte {
	var b bytes.Buffer
	b.Grow(cols * paneRows * 2)
	b.WriteString(resetScrollRegion)
	b.WriteString("\x1b[?25l")

	var activeRect *paneRect
	for i := range layout.Panes {
		r := layout.Panes[i]
		if r.PaneID == activePaneID {
			cp := r
			activeRect = &cp
		}
		emu := emus[r.PaneID]
		for row := 0; row < r.H; row++ {
			fmt.Fprintf(&b, "\x1b[%d;%dH", r.Y+row+1, r.X+1)
			if emu != nil {
				b.WriteString(emu.RenderRowFixed(row))
			} else {
				for k := 0; k < r.W; k++ {
					b.WriteByte(' ')
				}
			}
		}
	}

	// Build divider masks so intersections draw ┼ / ┬ / ┴ / ├ / ┤ cleanly.
	type coord struct{ x, y int }
	masks := make(map[coord]borderMask)
	for _, seg := range layout.Dividers {
		if seg.Horizontal {
			for dx := 0; dx < seg.Len; dx++ {
				cx, cy := seg.X+dx, seg.Y
				m := masks[coord{cx, cy}]
				if dx > 0 {
					m |= maskLeft
				}
				if dx < seg.Len-1 {
					m |= maskRight
				}
				if seg.Len == 1 {
					m |= maskLeft | maskRight
				}
				masks[coord{cx, cy}] = m
			}
		} else {
			for dy := 0; dy < seg.Len; dy++ {
				cx, cy := seg.X, seg.Y+dy
				m := masks[coord{cx, cy}]
				if dy > 0 {
					m |= maskUp
				}
				if dy < seg.Len-1 {
					m |= maskDown
				}
				if seg.Len == 1 {
					m |= maskUp | maskDown
				}
				masks[coord{cx, cy}] = m
			}
		}
	}

	touchesActive := func(cx, cy int) bool {
		if activeRect == nil {
			return false
		}
		ar := activeRect
		// Left or right vertical edge of active pane
		if (cx == ar.X-1 || cx == ar.X+ar.W) && cy >= ar.Y && cy < ar.Y+ar.H {
			return true
		}
		// Top or bottom horizontal edge of active pane
		if (cy == ar.Y-1 || cy == ar.Y+ar.H) && cx >= ar.X && cx < ar.X+ar.W {
			return true
		}
		return false
	}

	for pt, m := range masks {
		color := "\x1b[0;90m" // dim gray for inactive border
		if touchesActive(pt.x, pt.y) {
			color = "\x1b[0;36m" // bright cyan for active pane border
		}
		fmt.Fprintf(&b, "\x1b[%d;%dH%s%c\x1b[0m", pt.y+1, pt.x+1, color, borderGlyph(m))
	}

	if len(statusSeq) > 0 {
		b.Write(statusSeq)
	}

	// Place hardware cursor inside the active pane.
	if activeRect != nil {
		cx, cy := 0, 0
		if emu := emus[activeRect.PaneID]; emu != nil {
			mode := emu.Mode()
			cx, cy = mode.CursorX, mode.CursorY
		}
		if cx < 0 {
			cx = 0
		}
		if cx >= activeRect.W {
			cx = activeRect.W - 1
		}
		if cy < 0 {
			cy = 0
		}
		if cy >= activeRect.H {
			cy = activeRect.H - 1
		}
		fmt.Fprintf(&b, "\x1b[%d;%dH\x1b[?25h", activeRect.Y+cy+1, activeRect.X+cx+1)
	} else {
		b.WriteString("\x1b[?25h")
	}

	return b.Bytes()
}

type paneEventMsg struct {
	paneID string
	ev     sessionbackend.StreamEvent
	closed bool
}

// pumpMultiPane subscribes to every pane in win simultaneously, resizes each pane to its exact
// tiled dimensions, composites them side-by-side / top-to-bottom with box-drawing borders, and
// routes keyboard input to the focused pane.
func pumpMultiPane(
	ctx context.Context,
	backend sessionbackend.SessionBackend,
	layoutBackend sessionbackend.LayoutBackend,
	sessionID string,
	win sessionbackend.Window,
	activePaneID string,
	clientID string,
	inCh <-chan []byte,
	inErrCh <-chan error,
	resizeCh <-chan struct{},
	selectCellCh <-chan [2]int,
	onActivePane func(string),
	curCols, curRows *atomic.Uint32,
	paneRowsFor func(uint16) uint16,
	filter *PrefixFilter,
	writeOut func([]byte) error,
	buildStatusSeq func(pane string, prefixPending bool) []byte,
) (switchPane string, detached bool, exited bool, err error) {
	paneIDs := win.Layout.PaneIDs()
	if len(paneIDs) == 0 {
		return "", false, true, nil
	}
	if !win.Layout.ContainsPane(activePaneID) {
		activePaneID = win.ActivePaneID
		if !win.Layout.ContainsPane(activePaneID) {
			activePaneID = paneIDs[0]
		}
	}
	if onActivePane != nil {
		onActivePane(activePaneID)
	}

	cols := int(curCols.Load())
	pRows := int(paneRowsFor(uint16(curRows.Load())))
	cellLay := computeCellLayout(win.Layout, cols, pRows)

	rectByPane := make(map[string]paneRect, len(cellLay.Panes))
	for _, r := range cellLay.Panes {
		rectByPane[r.PaneID] = r
	}

	// Claim control, resize each pane to its tiled cell budget, and subscribe to every pane stream.
	subCtx, cancelSub := context.WithCancel(ctx)
	defer cancelSub()

	controlGens := make(map[string]uint64, len(paneIDs))
	streams := make(map[string]sessionbackend.PaneStream, len(paneIDs))
	emus := make(map[string]*sessionhost.Emulator, len(paneIDs))

	cleanup := func() {
		cancelSub()
		for pid, st := range streams {
			_ = st.Close()
			if gen := controlGens[pid]; gen > 0 {
				_ = backend.ReleaseControl(context.Background(), sessionbackend.Target{SessionID: sessionID, PaneID: pid}, clientID, gen)
			}
		}
	}
	defer cleanup()

	evCh := make(chan paneEventMsg, 256)
	var wg sync.WaitGroup

	for _, pid := range paneIDs {
		r, ok := rectByPane[pid]
		if !ok {
			continue
		}
		target := sessionbackend.Target{SessionID: sessionID, PaneID: pid}
		lease, lerr := backend.ClaimControl(subCtx, target, clientID)
		if lerr != nil {
			continue
		}
		controlGens[pid] = lease.ControlGen
		_ = backend.Resize(subCtx, target, lease.ControlGen, uint16(r.W), uint16(r.H))
		emus[pid] = sessionhost.NewEmulator(uint16(r.W), uint16(r.H), 1)

		stream, serr := backend.Attach(subCtx, target, sessionbackend.AttachOpts{ClientID: clientID})
		if serr != nil {
			continue
		}
		streams[pid] = stream

		wg.Add(1)
		go func(id string, s sessionbackend.PaneStream) {
			defer wg.Done()
			for {
				select {
				case <-subCtx.Done():
					return
				case ev, ok := <-s.Events():
					if !ok {
						select {
						case evCh <- paneEventMsg{paneID: id, closed: true}:
						case <-subCtx.Done():
						}
						return
					}
					select {
					case evCh <- paneEventMsg{paneID: id, ev: ev}:
					case <-subCtx.Done():
						return
					}
				}
			}
		}(pid, stream)
	}
	defer func() {
		cancelSub()
		for _, st := range streams {
			_ = st.Close()
		}
		wg.Wait()
	}()

	if len(streams) == 0 {
		return "", false, true, nil
	}

	writeInput := func(pid string, data []byte) error {
		if len(data) == 0 {
			return nil
		}
		target := sessionbackend.Target{SessionID: sessionID, PaneID: pid}
		gen := controlGens[pid]
		werr := backend.WriteInput(subCtx, target, gen, data)
		if errors.Is(werr, sessionbackend.ErrStaleControl) {
			lease, cerr := backend.ClaimControl(subCtx, target, clientID)
			if cerr != nil {
				return cerr
			}
			controlGens[pid] = lease.ControlGen
			werr = backend.WriteInput(subCtx, target, lease.ControlGen, data)
		}
		return werr
	}

	renderNow := func() error {
		c := int(curCols.Load())
		pr := int(paneRowsFor(uint16(curRows.Load())))
		statusSeq := buildStatusSeq(activePaneID, filter.Pending())
		frame := renderCompositeFrame(cellLay, emus, activePaneID, statusSeq, c, pr)
		return writeOut(frame)
	}

	// Clear terminal once on entering composite view, then flush coalesced frames at ~60fps.
	if err := writeOut([]byte(clearScreenHome)); err != nil {
		return "", false, false, err
	}
	if err := renderNow(); err != nil {
		return "", false, false, err
	}

	dirty := false
	ticker := time.NewTicker(16 * time.Millisecond)
	defer ticker.Stop()

	focusPane := func(next string) {
		if next == "" || next == activePaneID || !win.Layout.ContainsPane(next) {
			return
		}
		activePaneID = next
		if onActivePane != nil {
			onActivePane(next)
		}
		if layoutBackend != nil {
			_, _ = layoutBackend.FocusPane(subCtx, sessionID, win.ID, next)
		}
		_ = renderNow()
		dirty = false
	}

	for {
		select {
		case <-ctx.Done():
			return "", true, false, nil

		case pt, ok := <-selectCellCh:
			if !ok {
				selectCellCh = nil
				continue
			}
			for _, r := range cellLay.Panes {
				if pt[0] >= r.X && pt[0] < r.X+r.W && pt[1] >= r.Y && pt[1] < r.Y+r.H {
					focusPane(r.PaneID)
					break
				}
			}

		case <-resizeCh:
			c := int(curCols.Load())
			pr := int(paneRowsFor(uint16(curRows.Load())))
			cellLay = computeCellLayout(win.Layout, c, pr)
			for _, r := range cellLay.Panes {
				rectByPane[r.PaneID] = r
				if emu := emus[r.PaneID]; emu != nil {
					emu.Resize(uint16(r.W), uint16(r.H))
				}
				if gen := controlGens[r.PaneID]; gen > 0 {
					_ = backend.Resize(subCtx, sessionbackend.Target{SessionID: sessionID, PaneID: r.PaneID}, gen, uint16(r.W), uint16(r.H))
				}
			}
			_ = writeOut([]byte(clearScreenHome))
			if err := renderNow(); err != nil {
				return "", false, false, err
			}
			dirty = false

		case <-ticker.C:
			if dirty {
				if err := renderNow(); err != nil {
					return "", false, false, err
				}
				dirty = false
			}

		case msg := <-evCh:
			if msg.closed || msg.ev.Kind == sessionbackend.EventExited {
				// Re-enter outer loop so remaining sibling panes expand cleanly.
				next := activePaneID
				if msg.paneID == activePaneID {
					if candidate, ok := pickNextPane(subCtx, backend, sessionID, activePaneID); ok && candidate != activePaneID {
						next = candidate
					} else {
						return "", false, true, nil
					}
				}
				return next, false, false, nil
			}
			switch msg.ev.Kind {
			case sessionbackend.EventSnapshot:
				if r, ok := rectByPane[msg.paneID]; ok {
					emu := sessionhost.NewEmulator(uint16(r.W), uint16(r.H), 1)
					emu.Feed(msg.ev.Data)
					emus[msg.paneID] = emu
					dirty = true
				}
			case sessionbackend.EventOutput:
				if emu := emus[msg.paneID]; emu != nil && len(msg.ev.Data) > 0 {
					emu.Feed(msg.ev.Data)
					dirty = true
				}
			case sessionbackend.EventLayoutChanged:
				if msg.ev.Window != nil && msg.ev.Window.Version != win.Version {
					return activePaneID, false, false, nil
				}
			case sessionbackend.EventResyncNeeded:
				return activePaneID, false, false, nil
			}

		case chunk := <-inCh:
			cleaned := FilterAutoReplies(chunk)
			if len(cleaned) == 0 {
				continue
			}
			wasPending := filter.Pending()
			actions := filter.Feed(cleaned)
			nowPending := filter.Pending()
			if nowPending != wasPending {
				_ = renderNow()
				dirty = false
			}
			for _, act := range actions {
				switch act.Kind {
				case ActionForward:
					if err := writeInput(activePaneID, act.Data); err != nil {
						return "", false, false, err
					}
				case ActionDetach:
					return "", true, false, nil
				case ActionNextPane:
					for i, pid := range paneIDs {
						if pid == activePaneID {
							focusPane(paneIDs[(i+1)%len(paneIDs)])
							break
						}
					}
				case ActionFocusLeft:
					if nb, ok := win.FindNeighbor(activePaneID, sessionbackend.FocusLeft); ok {
						focusPane(nb)
					}
				case ActionFocusRight:
					if nb, ok := win.FindNeighbor(activePaneID, sessionbackend.FocusRight); ok {
						focusPane(nb)
					}
				case ActionFocusUp:
					if nb, ok := win.FindNeighbor(activePaneID, sessionbackend.FocusUp); ok {
						focusPane(nb)
					}
				case ActionFocusDown:
					if nb, ok := win.FindNeighbor(activePaneID, sessionbackend.FocusDown); ok {
						focusPane(nb)
					}
				case ActionSplitH, ActionSplitV:
					dir := sessionbackend.SplitHorizontal
					if act.Kind == ActionSplitV {
						dir = sessionbackend.SplitVertical
					}
					c := uint16(curCols.Load())
					pr := paneRowsFor(uint16(curRows.Load()))
					if r, ok := rectByPane[activePaneID]; ok {
						c, pr = uint16(r.W), uint16(r.H)
					}
					if newPaneID, ok := splitCurrentPane(subCtx, layoutBackend, sessionID, activePaneID, dir, c, pr); ok {
						return newPaneID, false, false, nil
					}
				case ActionClosePane:
					res := closeCurrentPane(subCtx, backend, layoutBackend, sessionID, activePaneID)
					if res.exited {
						return "", false, true, nil
					}
					if res.switchPane != "" {
						return res.switchPane, false, false, nil
					}
				case ActionNewWindow:
					c := uint16(curCols.Load())
					pr := paneRowsFor(uint16(curRows.Load()))
					if pane, ok := createAndSelectWindow(subCtx, layoutBackend, sessionID, c, pr); ok {
						return pane, false, false, nil
					}
				case ActionNextWindow:
					if pane, ok := stepWindow(subCtx, backend, layoutBackend, sessionID, activePaneID, +1); ok {
						return pane, false, false, nil
					}
				case ActionPrevWindow:
					if pane, ok := stepWindow(subCtx, backend, layoutBackend, sessionID, activePaneID, -1); ok {
						return pane, false, false, nil
					}
				case ActionSelectWindow:
					if pane, ok := selectWindowByNumber(subCtx, backend, layoutBackend, sessionID, act.Index); ok {
						return pane, false, false, nil
					}
				case ActionCloseWindow:
					res := closeCurrentWindow(subCtx, backend, layoutBackend, sessionID, activePaneID)
					if res.exited {
						return "", false, true, nil
					}
					if res.switchPane != "" {
						return res.switchPane, false, false, nil
					}
				case ActionOpenMenu:
					c := uint16(curCols.Load())
					pr := paneRowsFor(uint16(curRows.Load()))
					res, oerr := runCommandMenu(subCtx, backend, layoutBackend, sessionID, activePaneID, inCh, inErrCh, writeOut, c, pr)
					if oerr != nil {
						return "", false, false, oerr
					}
					if res.detached {
						return "", true, false, nil
					}
					if res.exited {
						return "", false, true, nil
					}
					if res.switchPane != "" {
						return res.switchPane, false, false, nil
					}
					return activePaneID, false, false, nil
				case ActionOpenWindowSwitcher:
					c := uint16(curCols.Load())
					pr := paneRowsFor(uint16(curRows.Load()))
					res, oerr := runWindowSwitcher(subCtx, backend, layoutBackend, sessionID, activePaneID, inCh, inErrCh, writeOut, c, pr)
					if oerr != nil {
						return "", false, false, oerr
					}
					if res.detached {
						return "", true, false, nil
					}
					if res.exited {
						return "", false, true, nil
					}
					if res.switchPane != "" {
						return res.switchPane, false, false, nil
					}
					return activePaneID, false, false, nil
				}
			}

		case rerr := <-inErrCh:
			if errors.Is(rerr, io.EOF) {
				return "", true, false, nil
			}
			return "", false, false, rerr
		}
	}
}
