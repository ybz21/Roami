package nativeattach

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"math"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionhost"
)

const (
	enableMouseClickANSI  = "\x1b[?1000h\x1b[?1006h"
	disableMouseClickANSI = "\x1b[?1006l\x1b[?1000l"
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

// sameLayoutTree reports whether two split trees have identical pane topology and ratios,
// so pure ActivePaneID focus changes do not trigger a full multi-pane reconnect.
func sameLayoutTree(a, b *sessionbackend.LayoutNode) bool {
	if a == nil || b == nil {
		return a == b
	}
	if a.Kind != b.Kind || a.PaneID != b.PaneID || a.Dir != b.Dir || math.Abs(a.Ratio-b.Ratio) > 1e-6 {
		return false
	}
	return sameLayoutTree(a.First, b.First) && sameLayoutTree(a.Second, b.Second)
}

type sgrMouseClick struct {
	col int // 0-based cell X
	row int // 0-based cell Y
}

// extractSGRMouseClicks strips both SGR (\x1b[<btn;col;rowM/m) and legacy X10 (\x1b[M<cb><cx><cy>)
// mouse sequences from raw input and returns left-button press coordinates so clicking a pane focuses it.
func extractSGRMouseClicks(data []byte) (remaining []byte, clicks []sgrMouseClick) {
	if !bytes.Contains(data, []byte("\x1b[<")) && !bytes.Contains(data, []byte("\x1b[M")) {
		return data, nil
	}
	out := make([]byte, 0, len(data))
	i := 0
	for i < len(data) {
		if i+3 < len(data) && data[i] == 0x1b && data[i+1] == '[' && data[i+2] == '<' {
			j := i + 3
			for j < len(data) && ((data[j] >= '0' && data[j] <= '9') || data[j] == ';') {
				j++
			}
			if j < len(data) && (data[j] == 'M' || data[j] == 'm') {
				kind := data[j]
				body := string(data[i+3 : j])
				parts := bytes.Split([]byte(body), []byte(";"))
				if len(parts) == 3 && kind == 'M' {
					btn, err1 := strconv.Atoi(string(parts[0]))
					col, err2 := strconv.Atoi(string(parts[1]))
					row, err3 := strconv.Atoi(string(parts[2]))
					if err1 == nil && err2 == nil && err3 == nil && btn == 0 && col >= 1 && row >= 1 {
						clicks = append(clicks, sgrMouseClick{col: col - 1, row: row - 1})
					}
				}
				i = j + 1
				continue
			}
		}
		// Legacy X10 normal mouse report: ESC [ M cb cx cy (coordinates are byte - 33).
		if i+5 < len(data) && data[i] == 0x1b && data[i+1] == '[' && data[i+2] == 'M' {
			cb := int(data[i+3]) - 32
			cx := int(data[i+4]) - 33
			cy := int(data[i+5]) - 33
			if cb == 0 && cx >= 0 && cy >= 0 {
				clicks = append(clicks, sgrMouseClick{col: cx, row: cy})
			}
			i += 6
			continue
		}
		out = append(out, data[i])
		i++
	}
	return out, clicks
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
		if (cx == ar.X-1 || cx == ar.X+ar.W) && cy >= ar.Y && cy < ar.Y+ar.H {
			return true
		}
		if (cy == ar.Y-1 || cy == ar.Y+ar.H) && cx >= ar.X && cx < ar.X+ar.W {
			return true
		}
		return false
	}

	// Draw directional arrows (◀/▶/▲/▼) on the divider pointing at the focused pane so focus is unmistakable.
	focusPointer := func(cx, cy int) (rune, bool) {
		if activeRect == nil {
			return 0, false
		}
		ar := activeRect
		if cy == ar.Y && cx == ar.X+ar.W {
			return '◀', true
		}
		if cy == ar.Y && cx == ar.X-1 {
			return '▶', true
		}
		if cx == ar.X && cy == ar.Y+ar.H {
			return '▲', true
		}
		if cx == ar.X && cy == ar.Y-1 {
			return '▼', true
		}
		return 0, false
	}

	for pt, m := range masks {
		if arrow, ok := focusPointer(pt.x, pt.y); ok {
			fmt.Fprintf(&b, "\x1b[%d;%dH\x1b[1;36m%c\x1b[0m", pt.y+1, pt.x+1, arrow)
			continue
		}
		color := "\x1b[0;90m"
		if touchesActive(pt.x, pt.y) {
			color = "\x1b[0;36m"
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
// routes keyboard + click input to the focused pane.
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
	moveCursorCh <-chan [2]int,
	onActivePane func(string),
	curCols, curRows *atomic.Uint32,
	paneRowsFor func(uint16) uint16,
	filter *PrefixFilter,
	writeOut func([]byte) error,
	buildStatusSeq func(pane string, prefixPending bool) []byte,
	enableCLIMouse bool,
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
		if enableCLIMouse {
			_ = writeOut([]byte(disableMouseClickANSI))
		}
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

	// Clear terminal once on entering composite view, enable CLI mouse click-to-focus, and flush at ~60fps.
	if err := writeOut([]byte(clearScreenHome)); err != nil {
		return "", false, false, err
	}
	if enableCLIMouse {
		_ = writeOut([]byte(enableMouseClickANSI))
	}
	if err := renderNow(); err != nil {
		return "", false, false, err
	}

	dirty := false
	var lastSwitchAt time.Time
	ticker := time.NewTicker(16 * time.Millisecond)
	defer ticker.Stop()

	focusPane := func(next string) {
		if next == "" || next == activePaneID || !win.Layout.ContainsPane(next) {
			return
		}
		activePaneID = next
		lastSwitchAt = time.Now()
		if onActivePane != nil {
			onActivePane(next)
		}
		if layoutBackend != nil {
			if updated, err := layoutBackend.FocusPane(subCtx, sessionID, win.ID, next); err == nil {
				win.Version = updated.Version
				win.ActivePaneID = updated.ActivePaneID
			}
		}
		_ = renderNow()
		dirty = false
	}

	focusAtCell := func(col, row int) {
		for _, r := range cellLay.Panes {
			if col >= r.X && col < r.X+r.W && row >= r.Y && row < r.Y+r.H {
				focusPane(r.PaneID)
				return
			}
		}
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
			focusAtCell(pt[0], pt[1])

		case pt, ok := <-moveCursorCh:
			if !ok {
				moveCursorCh = nil
				continue
			}
			// Clicking a different pane focuses it first; don't also fire cursor arrows on the same click.
			if time.Since(lastSwitchAt) < 350*time.Millisecond {
				continue
			}
			if r, ok := rectByPane[activePaneID]; ok {
				if pt[0] >= r.X && pt[0] < r.X+r.W && pt[1] >= r.Y && pt[1] < r.Y+r.H {
					target := sessionbackend.Target{SessionID: sessionID, PaneID: activePaneID}
					_ = backend.MoveCursor(subCtx, target, controlGens[activePaneID], pt[0]-r.X, pt[1]-r.Y)
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
				if msg.ev.Window != nil {
					if !sameLayoutTree(win.Layout, msg.ev.Window.Layout) {
						return activePaneID, false, false, nil
					}
					win.Version = msg.ev.Window.Version
					if msg.ev.Window.ActivePaneID != "" && msg.ev.Window.ActivePaneID != activePaneID && win.Layout.ContainsPane(msg.ev.Window.ActivePaneID) {
						activePaneID = msg.ev.Window.ActivePaneID
						if onActivePane != nil {
							onActivePane(activePaneID)
						}
						dirty = true
					}
				}
			case sessionbackend.EventResyncNeeded:
				return activePaneID, false, false, nil
			}

		case chunk := <-inCh:
			cleaned := FilterAutoReplies(chunk)
			if len(cleaned) == 0 {
				continue
			}
			// Handle SGR mouse clicks (CLI click-to-focus pane) before forwarding bytes to the shell.
			cleaned, clicks := extractSGRMouseClicks(cleaned)
			for _, click := range clicks {
				focusAtCell(click.col, click.row)
			}
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
					if enableCLIMouse {
						_ = writeOut([]byte(disableMouseClickANSI))
					}
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
					if enableCLIMouse {
						_ = writeOut([]byte(disableMouseClickANSI))
					}
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
