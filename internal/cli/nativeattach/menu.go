package nativeattach

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/ybz21/Roami/internal/sessionbackend"
)

type overlayOutcome struct {
	switchPane string
	detached   bool
	exited     bool
	refresh    bool
}

type menuKeyKind uint8

const (
	menuKeyNone menuKeyKind = iota
	menuKeyUp
	menuKeyDown
	menuKeyLeft
	menuKeyRight
	menuKeyEnter
	menuKeyEsc
	menuKeyChar
)

type menuKey struct {
	kind menuKeyKind
	ch   byte
}

// menuInput buffers raw bytes from inCh so arrow keys split across SSH packets
// (\x1b then [A) or SS3 sequences (\x1bOA) parse reliably without falsely exiting on Esc.
type menuInput struct {
	inCh    <-chan []byte
	inErrCh <-chan error
	buf     []byte
}

func newMenuInput(inCh <-chan []byte, inErrCh <-chan error) *menuInput {
	return &menuInput{inCh: inCh, inErrCh: inErrCh}
}

func (m *menuInput) readChunk(ctx context.Context, timeout time.Duration) (bool, error) {
	if timeout > 0 {
		timer := time.NewTimer(timeout)
		defer timer.Stop()
		select {
		case <-ctx.Done():
			return false, context.Canceled
		case err := <-m.inErrCh:
			return false, err
		case chunk := <-m.inCh:
			cleaned := FilterAutoReplies(chunk)
			if len(cleaned) > 0 {
				m.buf = append(m.buf, cleaned...)
				return true, nil
			}
			return false, nil
		case <-timer.C:
			return false, nil
		}
	}
	for {
		select {
		case <-ctx.Done():
			return false, context.Canceled
		case err := <-m.inErrCh:
			return false, err
		case chunk := <-m.inCh:
			cleaned := FilterAutoReplies(chunk)
			if len(cleaned) > 0 {
				m.buf = append(m.buf, cleaned...)
				return true, nil
			}
		}
	}
}

func (m *menuInput) nextKey(ctx context.Context) (menuKey, error) {
	for len(m.buf) == 0 {
		if _, err := m.readChunk(ctx, 0); err != nil {
			return menuKey{}, err
		}
	}
	b := m.buf[0]
	if b == 0x1b {
		// Wait briefly for follow-up bytes so lone Esc exits while split \x1b[A / \x1bOA parses as arrow keys.
		for len(m.buf) < 3 {
			got, err := m.readChunk(ctx, 40*time.Millisecond)
			if err != nil {
				return menuKey{}, err
			}
			if !got {
				break
			}
			if len(m.buf) >= 2 && m.buf[1] != '[' && m.buf[1] != 'O' {
				break
			}
		}
		if len(m.buf) >= 3 && (m.buf[1] == '[' || m.buf[1] == 'O') {
			// Pressing F2 again inside the menu toggles it closed cleanly.
			if m.buf[1] == 'O' && m.buf[2] == 'Q' {
				m.buf = m.buf[3:]
				return menuKey{kind: menuKeyEsc}, nil
			}
			if m.buf[1] == '[' && len(m.buf) >= 5 && m.buf[2] == '1' && m.buf[3] == '2' && m.buf[4] == '~' {
				m.buf = m.buf[5:]
				return menuKey{kind: menuKeyEsc}, nil
			}
			code := m.buf[2]
			m.buf = m.buf[3:]
			switch code {
			case 'A':
				return menuKey{kind: menuKeyUp}, nil
			case 'B':
				return menuKey{kind: menuKeyDown}, nil
			case 'C':
				return menuKey{kind: menuKeyRight}, nil
			case 'D':
				return menuKey{kind: menuKeyLeft}, nil
			default:
				return menuKey{kind: menuKeyNone}, nil
			}
		}
		m.buf = m.buf[1:]
		return menuKey{kind: menuKeyEsc}, nil
	}

	m.buf = m.buf[1:]
	switch b {
	case '\r', '\n':
		return menuKey{kind: menuKeyEnter}, nil
	case 0x03: // Ctrl+C
		return menuKey{kind: menuKeyEsc}, nil
	default:
		return menuKey{kind: menuKeyChar, ch: b}, nil
	}
}

type menuItemKind uint8

const (
	menuItemHeader menuItemKind = iota
	menuItemWindow
	menuItemAction
)

type menuItem struct {
	kind       menuItemKind
	label      string
	shortcut   string
	actionKey  byte
	windowID   string
	paneID     string
	selectable bool
}

// runCommandMenu opens a centered, box-drawn interactive menu (`Ctrl+b m` / `Ctrl+b ?`).
// Users can navigate with ↑/↓ (or j/k) + Enter OR press any displayed shortcut key directly.
func runCommandMenu(
	ctx context.Context,
	backend sessionbackend.SessionBackend,
	layout sessionbackend.LayoutBackend,
	sessionID, currentPaneID string,
	inCh <-chan []byte,
	inErrCh <-chan error,
	writeOut func([]byte) error,
	cols, rows uint16,
) (overlayOutcome, error) {
	return runCommandMenuWithInput(ctx, backend, layout, sessionID, currentPaneID, newMenuInput(inCh, inErrCh), writeOut, cols, rows)
}

func runCommandMenuWithInput(
	ctx context.Context,
	backend sessionbackend.SessionBackend,
	layout sessionbackend.LayoutBackend,
	sessionID, currentPaneID string,
	mi *menuInput,
	writeOut func([]byte) error,
	cols, rows uint16,
) (overlayOutcome, error) {
	st, err := backend.Observe(ctx, sessionID)
	if err != nil {
		return overlayOutcome{refresh: true}, nil
	}

	items := buildCommandMenuItems(st, currentPaneID)
	selected := firstSelectableIndex(items)
	// Default cursor onto the first actionable split/menu command if only 1 window exists,
	// or onto the first non-current window if multiple windows exist for quick switching.
	if len(st.Windows) <= 1 {
		for i, it := range items {
			if it.kind == menuItemAction && it.selectable {
				selected = i
				break
			}
		}
	} else {
		for i, it := range items {
			if it.kind == menuItemWindow && it.windowID != st.ActiveWindowID {
				selected = i
				break
			}
		}
	}

	defer func() { _ = writeOut([]byte("\x1b[?25h")) }()

	execAction := func(actionKey byte) (overlayOutcome, bool, error) {
		switch {
		case actionKey == 'q' || actionKey == 'Q' || actionKey == 0x1b:
			return overlayOutcome{refresh: true}, true, nil
		case actionKey == 'd' || actionKey == 'D':
			return overlayOutcome{detached: true}, true, nil
		case actionKey == 'w' || actionKey == 'W':
			res, werr := runWindowSwitcherWithInput(ctx, backend, layout, sessionID, currentPaneID, mi, writeOut, cols, rows)
			return res, true, werr
		case actionKey == 'c' || actionKey == 'C':
			if pane, ok := createAndSelectWindow(ctx, layout, sessionID, cols, rows); ok {
				return overlayOutcome{switchPane: pane}, true, nil
			}
			return overlayOutcome{refresh: true}, true, nil
		case actionKey == 'n' || actionKey == 'N':
			if pane, ok := stepWindow(ctx, backend, layout, sessionID, currentPaneID, +1); ok {
				return overlayOutcome{switchPane: pane}, true, nil
			}
			return overlayOutcome{refresh: true}, true, nil
		case actionKey == 'p' || actionKey == 'P':
			if pane, ok := stepWindow(ctx, backend, layout, sessionID, currentPaneID, -1); ok {
				return overlayOutcome{switchPane: pane}, true, nil
			}
			return overlayOutcome{refresh: true}, true, nil
		case actionKey >= '1' && actionKey <= '9':
			if pane, ok := selectWindowByNumber(ctx, backend, layout, sessionID, int(actionKey-'0')); ok {
				return overlayOutcome{switchPane: pane}, true, nil
			}
			return overlayOutcome{}, false, nil
		case actionKey == '%' || actionKey == '|':
			if pane, ok := splitCurrentPane(ctx, layout, sessionID, currentPaneID, sessionbackend.SplitHorizontal, cols, rows); ok {
				return overlayOutcome{switchPane: pane}, true, nil
			}
			return overlayOutcome{refresh: true}, true, nil
		case actionKey == '"' || actionKey == '-':
			if pane, ok := splitCurrentPane(ctx, layout, sessionID, currentPaneID, sessionbackend.SplitVertical, cols, rows); ok {
				return overlayOutcome{switchPane: pane}, true, nil
			}
			return overlayOutcome{refresh: true}, true, nil
		case actionKey == 'o' || actionKey == 'O' || actionKey == '\t':
			if next, ok := pickNextPaneInWindow(ctx, backend, layout, sessionID, currentPaneID); ok && next != currentPaneID {
				return overlayOutcome{switchPane: next}, true, nil
			}
			return overlayOutcome{refresh: true}, true, nil
		case actionKey == 'x' || actionKey == 'X':
			return closeCurrentPane(ctx, backend, layout, sessionID, currentPaneID), true, nil
		case actionKey == '&':
			return closeCurrentWindow(ctx, backend, layout, sessionID, currentPaneID), true, nil
		}
		return overlayOutcome{}, false, nil
	}

	for {
		frame := renderCommandMenuBox(st, currentPaneID, items, selected, int(cols), int(rows))
		if err := writeOut([]byte(frame)); err != nil {
			return overlayOutcome{}, err
		}

		k, err := mi.nextKey(ctx)
		if err != nil {
			if err == context.Canceled {
				return overlayOutcome{detached: true}, nil
			}
			return overlayOutcome{}, err
		}
		switch k.kind {
		case menuKeyEsc:
			return overlayOutcome{refresh: true}, nil
		case menuKeyUp:
			selected = stepSelectable(items, selected, -1)
		case menuKeyDown:
			selected = stepSelectable(items, selected, +1)
		case menuKeyEnter:
			if selected >= 0 && selected < len(items) && items[selected].selectable {
				it := items[selected]
				if it.kind == menuItemWindow {
					if layout != nil {
						_ = layout.SelectWindow(ctx, sessionID, it.windowID)
						if it.paneID != "" {
							_, _ = layout.FocusPane(ctx, sessionID, it.windowID, it.paneID)
						}
					}
					return overlayOutcome{switchPane: it.paneID}, nil
				}
				if res, done, aerr := execAction(it.actionKey); done || aerr != nil {
					return res, aerr
				}
			}
		case menuKeyChar:
			switch k.ch {
			case 'j', 'J':
				selected = stepSelectable(items, selected, +1)
			case 'k', 'K':
				selected = stepSelectable(items, selected, -1)
			default:
				if res, done, aerr := execAction(k.ch); done || aerr != nil {
					return res, aerr
				}
			}
		}
	}
}

func buildCommandMenuItems(st sessionbackend.SessionState, currentPaneID string) []menuItem {
	var items []menuItem
	if len(st.Windows) > 0 {
		items = append(items, menuItem{kind: menuItemHeader, label: fmt.Sprintf("窗口直达（共 %d 个，按数字键或回车切换）", len(st.Windows))})
		for i, w := range st.Windows {
			name := w.Name
			if name == "" {
				name = w.ID
			}
			paneCount := 1
			activePane := w.ActivePaneID
			if w.Layout != nil {
				panes := w.Layout.PaneIDs()
				paneCount = len(panes)
				if activePane == "" && len(panes) > 0 {
					activePane = panes[0]
				}
			}
			mark := ""
			if w.ID == st.ActiveWindowID || (w.Layout != nil && w.Layout.ContainsPane(currentPaneID)) {
				mark = " [当前]"
			}
			shortcut := ""
			var aKey byte
			if i < 9 {
				shortcut = fmt.Sprintf("%d", i+1)
				aKey = byte('1' + i)
			}
			label := fmt.Sprintf("%d:%s (%d窗格)%s", i+1, name, paneCount, mark)
			items = append(items, menuItem{
				kind:       menuItemWindow,
				label:      label,
				shortcut:   shortcut,
				actionKey:  aKey,
				windowID:   w.ID,
				paneID:     activePane,
				selectable: true,
			})
		}
	}

	curPaneCount := 1
	for _, w := range st.Windows {
		if w.Layout != nil && (w.Layout.ContainsPane(currentPaneID) || w.ID == st.ActiveWindowID) {
			curPaneCount = len(w.Layout.PaneIDs())
			break
		}
	}
	closeLabel := "关闭当前窗口"
	if curPaneCount > 1 {
		closeLabel = "关闭当前窗格"
	}

	items = append(items,
		menuItem{kind: menuItemHeader, label: "常用操作"},
		menuItem{kind: menuItemAction, label: "左右分屏", shortcut: "|", actionKey: '|', selectable: true},
		menuItem{kind: menuItemAction, label: "上下分屏", shortcut: "-", actionKey: '-', selectable: true},
		menuItem{kind: menuItemAction, label: "切换窗格", shortcut: "Tab", actionKey: '\t', selectable: true},
		menuItem{kind: menuItemAction, label: "新建窗口", shortcut: "c", actionKey: 'c', selectable: true},
		menuItem{kind: menuItemAction, label: closeLabel, shortcut: "x", actionKey: 'x', selectable: true},
		menuItem{kind: menuItemAction, label: "放后台（脱离会话）", shortcut: "d", actionKey: 'd', selectable: true},
	)
	return items
}

func firstSelectableIndex(items []menuItem) int {
	for i, it := range items {
		if it.selectable {
			return i
		}
	}
	return 0
}

func stepSelectable(items []menuItem, cur, delta int) int {
	n := len(items)
	if n == 0 {
		return 0
	}
	for step := 1; step <= n; step++ {
		idx := (cur + delta*step + n*10) % n
		if items[idx].selectable {
			return idx
		}
	}
	return cur
}

func renderCommandMenuBox(st sessionbackend.SessionState, currentPaneID string, items []menuItem, selected, cols, rows int) string {
	label := st.Label
	if label == "" {
		label = st.SessionID
	}
	winIdx, winName := activeWindowLabel(st, currentPaneID)

	boxW := 60
	if cols > 0 && cols-4 < boxW {
		boxW = cols - 4
	}
	if boxW < 34 {
		boxW = 34
	}
	innerW := boxW - 2

	var boxLines []string
	title := fmt.Sprintf(" Roami 终端菜单 [%s] · %d:%s ", label, winIdx, winName)
	title = clipDisplay(title, innerW-2)
	titlePad := innerW - displayWidth(title) - 1
	if titlePad < 0 {
		titlePad = 0
	}
	boxLines = append(boxLines, "\x1b[36m╭─\x1b[1;36m"+title+"\x1b[0;36m"+strings.Repeat("─", titlePad)+"╮\x1b[0m")

	for i, it := range items {
		if it.kind == menuItemHeader {
			hdr := " " + clipDisplay(it.label, innerW-2)
			pad := innerW - displayWidth(hdr)
			if pad < 0 {
				pad = 0
			}
			boxLines = append(boxLines, "\x1b[36m│\x1b[0;2m"+hdr+strings.Repeat(" ", pad)+"\x1b[0;36m│\x1b[0m")
			continue
		}
		rightTag := ""
		if it.shortcut != "" {
			rightTag = "[" + it.shortcut + "] "
		}
		rightW := displayWidth(rightTag)
		prefix := "   "
		if i == selected {
			prefix = " ▸ "
		}
		avail := innerW - displayWidth(prefix) - rightW - 1
		if avail < 6 {
			avail = 6
		}
		text := clipDisplay(it.label, avail)
		gap := innerW - displayWidth(prefix) - displayWidth(text) - rightW
		if gap < 1 {
			gap = 1
		}
		lineContent := prefix + text + strings.Repeat(" ", gap) + rightTag
		if i == selected {
			boxLines = append(boxLines, "\x1b[36m│\x1b[1;30;46m"+padOrClipDisplay(lineContent, innerW)+"\x1b[0;36m│\x1b[0m")
		} else {
			boxLines = append(boxLines, "\x1b[36m│\x1b[0m"+prefix+text+strings.Repeat(" ", gap)+"\x1b[33m"+rightTag+"\x1b[0;36m│\x1b[0m")
		}
	}

	footer := " ↑/↓ 选择 · Enter 确认 · w 窗格预览 · Esc 返回 "
	footer = clipDisplay(footer, innerW-2)
	fPad := innerW - displayWidth(footer) - 1
	if fPad < 0 {
		fPad = 0
	}
	boxLines = append(boxLines, "\x1b[36m╰─\x1b[0;2m"+footer+"\x1b[0;36m"+strings.Repeat("─", fPad)+"╯\x1b[0m")

	startX := 1
	if cols > boxW {
		startX = (cols-boxW)/2 + 1
	}
	startY := 1
	if rows > len(boxLines) {
		startY = (rows-len(boxLines))/2 + 1
	}

	var b strings.Builder
	b.WriteString(resetScrollRegion)
	b.WriteString("\x1b[2J\x1b[H\x1b[?25l")
	for i, line := range boxLines {
		if rows > 0 && startY+i > rows {
			break
		}
		fmt.Fprintf(&b, "\x1b[%d;%dH%s", startY+i, startX, line)
	}
	return b.String()
}

type switcherRow struct {
	windowID    string
	windowIndex int
	windowName  string
	paneID      string
	preview     string
	isWindow    bool
	isActiveWin bool
	isActiveP   bool
}

// runWindowSwitcher opens an interactive window/pane tree picker (`Ctrl+b w`) with live pane previews.
func runWindowSwitcher(
	ctx context.Context,
	backend sessionbackend.SessionBackend,
	layout sessionbackend.LayoutBackend,
	sessionID, currentPaneID string,
	inCh <-chan []byte,
	inErrCh <-chan error,
	writeOut func([]byte) error,
	cols, rows uint16,
) (overlayOutcome, error) {
	return runWindowSwitcherWithInput(ctx, backend, layout, sessionID, currentPaneID, newMenuInput(inCh, inErrCh), writeOut, cols, rows)
}

func runWindowSwitcherWithInput(
	ctx context.Context,
	backend sessionbackend.SessionBackend,
	layout sessionbackend.LayoutBackend,
	sessionID, currentPaneID string,
	mi *menuInput,
	writeOut func([]byte) error,
	cols, rows uint16,
) (overlayOutcome, error) {
	selected := 0
	initialized := false
	defer func() { _ = writeOut([]byte("\x1b[?25h")) }()

	for {
		st, err := backend.Observe(ctx, sessionID)
		if err != nil || st.Status != sessionbackend.StatusAlive || len(st.Windows) == 0 {
			return overlayOutcome{exited: true}, nil
		}
		previews := fetchPanePreviews(ctx, backend, st)
		items := buildSwitcherRows(st, currentPaneID, previews)
		if len(items) == 0 {
			return overlayOutcome{refresh: true}, nil
		}
		if !initialized {
			for i, it := range items {
				if it.paneID == currentPaneID && (!it.isWindow || len(items) == len(st.Windows)) {
					selected = i
					break
				}
			}
			initialized = true
		}
		if selected >= len(items) {
			selected = len(items) - 1
		}
		if selected < 0 {
			selected = 0
		}

		if err := writeOut([]byte(renderSwitcherView(st, items, selected, int(cols), int(rows)))); err != nil {
			return overlayOutcome{}, err
		}

		k, err := mi.nextKey(ctx)
		if err != nil {
			if err == context.Canceled {
				return overlayOutcome{detached: true}, nil
			}
			return overlayOutcome{}, err
		}
		switch k.kind {
		case menuKeyEsc:
			return overlayOutcome{refresh: true}, nil
		case menuKeyUp:
			selected = (selected - 1 + len(items)) % len(items)
		case menuKeyDown:
			selected = (selected + 1) % len(items)
		case menuKeyEnter:
			it := items[selected]
			if layout != nil {
				_ = layout.SelectWindow(ctx, sessionID, it.windowID)
				if it.paneID != "" {
					_, _ = layout.FocusPane(ctx, sessionID, it.windowID, it.paneID)
				}
			}
			return overlayOutcome{switchPane: it.paneID}, nil
		case menuKeyChar:
			switch {
			case k.ch == 'q' || k.ch == 'Q':
				return overlayOutcome{refresh: true}, nil
			case k.ch == 'j' || k.ch == 'J':
				selected = (selected + 1) % len(items)
			case k.ch == 'k' || k.ch == 'K':
				selected = (selected - 1 + len(items)) % len(items)
			case k.ch >= '1' && k.ch <= '9':
				if pane, ok := selectWindowByNumber(ctx, backend, layout, sessionID, int(k.ch-'0')); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
			case k.ch == 'c' || k.ch == 'C':
				if pane, ok := createAndSelectWindow(ctx, layout, sessionID, cols, rows); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
			case k.ch == '%':
				it := items[selected]
				if pane, ok := splitCurrentPane(ctx, layout, sessionID, it.paneID, sessionbackend.SplitHorizontal, cols, rows); ok {
					if layout != nil {
						_ = layout.SelectWindow(ctx, sessionID, it.windowID)
					}
					return overlayOutcome{switchPane: pane}, nil
				}
			case k.ch == '"':
				it := items[selected]
				if pane, ok := splitCurrentPane(ctx, layout, sessionID, it.paneID, sessionbackend.SplitVertical, cols, rows); ok {
					if layout != nil {
						_ = layout.SelectWindow(ctx, sessionID, it.windowID)
					}
					return overlayOutcome{switchPane: pane}, nil
				}
			case k.ch == 'x' || k.ch == 'X':
				if layout != nil {
					it := items[selected]
					if it.isWindow {
						_ = layout.CloseWindow(ctx, sessionID, it.windowID)
					} else {
						_, _ = layout.ClosePane(ctx, sessionID, it.paneID)
					}
				}
			case k.ch == 'm' || k.ch == 'M':
				return runCommandMenuWithInput(ctx, backend, layout, sessionID, currentPaneID, mi, writeOut, cols, rows)
			case k.ch == 'd' || k.ch == 'D':
				return overlayOutcome{detached: true}, nil
			}
		}
	}
}

func fetchPanePreviews(ctx context.Context, backend sessionbackend.SessionBackend, st sessionbackend.SessionState) map[string]string {
	out := make(map[string]string)
	pCtx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
	defer cancel()
	for _, w := range st.Windows {
		if w.Layout == nil {
			continue
		}
		for _, pid := range w.Layout.PaneIDs() {
			capRes, err := backend.Capture(pCtx, sessionbackend.Target{SessionID: st.SessionID, PaneID: pid}, sessionbackend.CaptureOpts{Lines: 6})
			if err != nil {
				continue
			}
			lines := strings.Split(capRes.Text, "\n")
			fallback := ""
			for i := len(lines) - 1; i >= 0; i-- {
				line := strings.TrimSpace(lines[i])
				if line == "" {
					continue
				}
				if fallback == "" {
					fallback = line
				}
				// Skip bare shell prompts so the preview shows the last meaningful output/command.
				if line == "$" || line == "#" || line == "%" || line == ">" {
					continue
				}
				out[pid] = line
				break
			}
			if out[pid] == "" && fallback != "" {
				out[pid] = fallback
			}
		}
	}
	return out
}

func buildSwitcherRows(st sessionbackend.SessionState, currentPaneID string, previews map[string]string) []switcherRow {
	var rows []switcherRow
	for i, w := range st.Windows {
		name := w.Name
		if name == "" {
			name = w.ID
		}
		var panes []string
		if w.Layout != nil {
			panes = w.Layout.PaneIDs()
		}
		activePane := w.ActivePaneID
		if activePane == "" && len(panes) > 0 {
			activePane = panes[0]
		}
		isActiveWin := w.ID == st.ActiveWindowID
		rows = append(rows, switcherRow{
			windowID:    w.ID,
			windowIndex: i + 1,
			windowName:  name,
			paneID:      activePane,
			preview:     previews[activePane],
			isWindow:    true,
			isActiveWin: isActiveWin,
			isActiveP:   activePane == currentPaneID,
		})
		if len(panes) > 1 {
			for _, pid := range panes {
				rows = append(rows, switcherRow{
					windowID:    w.ID,
					windowIndex: i + 1,
					windowName:  name,
					paneID:      pid,
					preview:     previews[pid],
					isWindow:    false,
					isActiveWin: isActiveWin,
					isActiveP:   pid == currentPaneID,
				})
			}
		}
	}
	return rows
}

func renderSwitcherView(st sessionbackend.SessionState, items []switcherRow, selected, cols, rows int) string {
	label := st.Label
	if label == "" {
		label = st.SessionID
	}
	boxW := 78
	if cols > 0 && cols-4 < boxW {
		boxW = cols - 4
	}
	if boxW < 40 {
		boxW = 40
	}
	innerW := boxW - 2

	var boxLines []string
	title := fmt.Sprintf(" 切换窗口 / 窗格 [%s] ", label)
	title = clipDisplay(title, innerW-2)
	titlePad := innerW - displayWidth(title) - 1
	if titlePad < 0 {
		titlePad = 0
	}
	boxLines = append(boxLines, "\x1b[36m╭─\x1b[1;36m"+title+"\x1b[0;36m"+strings.Repeat("─", titlePad)+"╮\x1b[0m")

	for i, it := range items {
		prefix := "   "
		if i == selected {
			prefix = " ▸ "
		}
		var base string
		if it.isWindow {
			tag := ""
			if it.isActiveWin {
				tag = " [当前]"
			}
			base = fmt.Sprintf("[%d] %s (%s)%s", it.windowIndex, it.windowName, it.windowID, tag)
		} else {
			tag := ""
			if it.isActiveP {
				tag = " *"
			}
			base = fmt.Sprintf("  └─ 窗格 %s%s", it.paneID, tag)
		}
		previewPart := ""
		if it.preview != "" {
			rem := innerW - displayWidth(prefix) - displayWidth(base) - 4
			if rem >= 8 {
				previewPart = "  │ " + clipDisplay(it.preview, rem)
			}
		}
		line := prefix + base + previewPart
		if i == selected {
			boxLines = append(boxLines, "\x1b[36m│\x1b[1;30;46m"+padOrClipDisplay(line, innerW)+"\x1b[0;36m│\x1b[0m")
		} else {
			clippedBase := clipDisplay(prefix+base, innerW)
			rem := innerW - displayWidth(clippedBase)
			if previewPart != "" && rem > 0 {
				clippedPrev := clipDisplay(previewPart, rem)
				pad := innerW - displayWidth(clippedBase) - displayWidth(clippedPrev)
				if pad < 0 {
					pad = 0
				}
				boxLines = append(boxLines, "\x1b[36m│\x1b[0m"+clippedBase+"\x1b[2m"+clippedPrev+strings.Repeat(" ", pad)+"\x1b[0;36m│\x1b[0m")
			} else {
				pad := innerW - displayWidth(clippedBase)
				if pad < 0 {
					pad = 0
				}
				boxLines = append(boxLines, "\x1b[36m│\x1b[0m"+clippedBase+strings.Repeat(" ", pad)+"\x1b[0;36m│\x1b[0m")
			}
		}
	}

	footer := " ↑/↓ 选择 · Enter 进入 · 1-9 直达 · c 新建 · %/\" 分屏 · x 关闭 · m 菜单 · Esc 返回 "
	footer = clipDisplay(footer, innerW-2)
	fPad := innerW - displayWidth(footer) - 1
	if fPad < 0 {
		fPad = 0
	}
	boxLines = append(boxLines, "\x1b[36m╰─\x1b[0;2m"+footer+"\x1b[0;36m"+strings.Repeat("─", fPad)+"╯\x1b[0m")

	startX := 1
	if cols > boxW {
		startX = (cols-boxW)/2 + 1
	}
	startY := 1
	if rows > len(boxLines) {
		startY = (rows-len(boxLines))/2 + 1
	}

	var b strings.Builder
	b.WriteString(resetScrollRegion)
	b.WriteString("\x1b[2J\x1b[H\x1b[?25l")
	for i, line := range boxLines {
		if rows > 0 && startY+i > rows {
			break
		}
		fmt.Fprintf(&b, "\x1b[%d;%dH%s", startY+i, startX, line)
	}
	return b.String()
}

func activeWindowLabel(st sessionbackend.SessionState, currentPaneID string) (int, string) {
	for i, w := range st.Windows {
		if w.Layout != nil && w.Layout.ContainsPane(currentPaneID) {
			name := w.Name
			if name == "" {
				name = w.ID
			}
			return i + 1, name
		}
	}
	for i, w := range st.Windows {
		if w.ID == st.ActiveWindowID {
			name := w.Name
			if name == "" {
				name = w.ID
			}
			return i + 1, name
		}
	}
	return 1, "main"
}

func createAndSelectWindow(ctx context.Context, layout sessionbackend.LayoutBackend, sessionID string, cols, rows uint16) (string, bool) {
	if layout == nil {
		return "", false
	}
	win, err := layout.NewWindow(ctx, sessionID, sessionbackend.WindowSpec{
		Cols:       cols,
		Rows:       rows,
		LoginShell: true,
	})
	if err != nil || win.ActivePaneID == "" {
		return "", false
	}
	_ = layout.SelectWindow(ctx, sessionID, win.ID)
	return win.ActivePaneID, true
}

func selectWindowByNumber(ctx context.Context, backend sessionbackend.SessionBackend, layout sessionbackend.LayoutBackend, sessionID string, num int) (string, bool) {
	if num < 1 {
		return "", false
	}
	st, err := backend.Observe(ctx, sessionID)
	if err != nil || num > len(st.Windows) {
		return "", false
	}
	w := st.Windows[num-1]
	if layout != nil {
		_ = layout.SelectWindow(ctx, sessionID, w.ID)
	}
	if w.ActivePaneID != "" {
		return w.ActivePaneID, true
	}
	if w.Layout != nil {
		if panes := w.Layout.PaneIDs(); len(panes) > 0 {
			return panes[0], true
		}
	}
	return "", false
}

func stepWindow(ctx context.Context, backend sessionbackend.SessionBackend, layout sessionbackend.LayoutBackend, sessionID, currentPaneID string, delta int) (string, bool) {
	st, err := backend.Observe(ctx, sessionID)
	if err != nil || len(st.Windows) < 2 {
		return "", false
	}
	cur := 0
	for i, w := range st.Windows {
		if (w.Layout != nil && w.Layout.ContainsPane(currentPaneID)) || w.ID == st.ActiveWindowID {
			cur = i
			break
		}
	}
	next := (cur + delta + len(st.Windows)) % len(st.Windows)
	w := st.Windows[next]
	if layout != nil {
		_ = layout.SelectWindow(ctx, sessionID, w.ID)
	}
	if w.ActivePaneID != "" {
		return w.ActivePaneID, true
	}
	if w.Layout != nil {
		if panes := w.Layout.PaneIDs(); len(panes) > 0 {
			return panes[0], true
		}
	}
	return "", false
}

func splitCurrentPane(ctx context.Context, layout sessionbackend.LayoutBackend, sessionID, paneID string, dir sessionbackend.SplitDir, cols, rows uint16) (string, bool) {
	if layout == nil {
		return "", false
	}
	_, newPaneID, err := layout.SplitPane(ctx, sessionID, paneID, sessionbackend.SplitSpec{
		Dir:        dir,
		Cols:       cols,
		Rows:       rows,
		LoginShell: true,
	})
	if err != nil || newPaneID == "" {
		return "", false
	}
	return newPaneID, true
}

func closeCurrentPane(ctx context.Context, backend sessionbackend.SessionBackend, layout sessionbackend.LayoutBackend, sessionID, paneID string) overlayOutcome {
	if layout == nil {
		return overlayOutcome{refresh: true}
	}
	win, err := layout.ClosePane(ctx, sessionID, paneID)
	if err != nil {
		return overlayOutcome{refresh: true}
	}
	if win != nil && win.ActivePaneID != "" {
		return overlayOutcome{switchPane: win.ActivePaneID}
	}
	if next, ok := pickNextPane(ctx, backend, sessionID, paneID); ok && next != paneID {
		return overlayOutcome{switchPane: next}
	}
	return overlayOutcome{exited: true}
}

func closeCurrentWindow(ctx context.Context, backend sessionbackend.SessionBackend, layout sessionbackend.LayoutBackend, sessionID, paneID string) overlayOutcome {
	if layout == nil {
		return overlayOutcome{refresh: true}
	}
	st, err := backend.Observe(ctx, sessionID)
	if err != nil {
		return overlayOutcome{refresh: true}
	}
	winID := st.ActiveWindowID
	for _, w := range st.Windows {
		if w.Layout != nil && w.Layout.ContainsPane(paneID) {
			winID = w.ID
			break
		}
	}
	if winID == "" {
		return overlayOutcome{refresh: true}
	}
	if err := layout.CloseWindow(ctx, sessionID, winID); err != nil {
		return overlayOutcome{refresh: true}
	}
	nextSt, err := backend.Observe(ctx, sessionID)
	if err != nil || nextSt.Status != sessionbackend.StatusAlive || nextSt.ActivePaneID == "" {
		return overlayOutcome{exited: true}
	}
	return overlayOutcome{switchPane: nextSt.ActivePaneID}
}

func pickNextPaneInWindow(ctx context.Context, backend sessionbackend.SessionBackend, layout sessionbackend.LayoutBackend, sessionID, currentPaneID string) (string, bool) {
	st, err := backend.Observe(ctx, sessionID)
	if err != nil || st.Status != sessionbackend.StatusAlive {
		return "", false
	}
	// Prefer cycling panes inside the current window first, just like tmux `Ctrl+b o`.
	for _, w := range st.Windows {
		if w.Layout != nil && w.Layout.ContainsPane(currentPaneID) {
			panes := w.Layout.PaneIDs()
			if len(panes) > 1 {
				for i, id := range panes {
					if id == currentPaneID {
						next := panes[(i+1)%len(panes)]
						if layout != nil {
							_, _ = layout.FocusPane(ctx, sessionID, w.ID, next)
						}
						return next, true
					}
				}
			}
		}
	}
	return pickNextPane(ctx, backend, sessionID, currentPaneID)
}
