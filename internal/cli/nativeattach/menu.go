package nativeattach

import (
	"context"
	"fmt"
	"strings"

	"github.com/ybz21/Roami/internal/sessionbackend"
)

type overlayOutcome struct {
	switchPane string
	detached   bool
	exited     bool
	refresh    bool
}

type switcherRow struct {
	windowID    string
	windowIndex int
	windowName  string
	paneID      string
	isWindow    bool
	isActiveWin bool
	isActiveP   bool
}

// runCommandMenu opens a tmux-like interactive command menu overlay (`Ctrl+b m` / `Ctrl+b ?`).
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
	st, err := backend.Observe(ctx, sessionID)
	if err != nil {
		return overlayOutcome{refresh: true}, nil
	}

	label := st.Label
	if label == "" {
		label = st.SessionID
	}
	winIdx, winName := activeWindowLabel(st, currentPaneID)

	var b strings.Builder
	b.WriteString(resetScrollRegion)
	b.WriteString("\x1b[2J\x1b[H\x1b[?25l")
	fmt.Fprintf(&b, "\x1b[1;36m=== Roami 终端菜单 [%s] ===\x1b[0m\r\n", label)
	fmt.Fprintf(&b, "\x1b[2m当前位置：窗口 %d:%s · 窗格 %s（共 %d 个窗口）\x1b[0m\r\n\r\n", winIdx, winName, currentPaneID, len(st.Windows))
	lines := []string{
		"  [w]  切换窗口 / 查看分屏列表（方向键选择）",
		"  [c]  新建窗口并切过去",
		"  [n]  下一个窗口        [p]  上一个窗口",
		"  [1-9] 按序号直接切换窗口",
		"  [%]  左右分屏          [\"]  上下分屏",
		"  [o]  切换到下一个窗格",
		"  [x]  关闭当前窗格      [&]  关闭当前窗口",
		"  [d]  脱离会话（保持后台运行）",
		"  [q / Esc]  返回终端",
	}
	for _, line := range lines {
		b.WriteString(line)
		b.WriteString("\r\n")
	}
	b.WriteString("\r\n\x1b[33m按对应按键执行：\x1b[0m")
	if err := writeOut([]byte(b.String())); err != nil {
		return overlayOutcome{}, err
	}
	defer func() { _ = writeOut([]byte("\x1b[?25h")) }()

	for {
		select {
		case <-ctx.Done():
			return overlayOutcome{detached: true}, nil
		case rerr := <-inErrCh:
			return overlayOutcome{}, rerr
		case chunk := <-inCh:
			cleaned := FilterAutoReplies(chunk)
			if len(cleaned) == 0 {
				continue
			}
			key := cleaned[0]
			switch {
			case key == 'q' || key == 'Q' || key == 0x1b || key == 0x03 || key == '\r' || key == '\n':
				return overlayOutcome{refresh: true}, nil
			case key == 'd' || key == 'D':
				return overlayOutcome{detached: true}, nil
			case key == 'w' || key == 'W':
				return runWindowSwitcher(ctx, backend, layout, sessionID, currentPaneID, inCh, inErrCh, writeOut, cols, rows)
			case key == 'c' || key == 'C':
				if pane, ok := createAndSelectWindow(ctx, layout, sessionID, cols, rows); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
				return overlayOutcome{refresh: true}, nil
			case key == 'n' || key == 'N':
				if pane, ok := stepWindow(ctx, backend, layout, sessionID, currentPaneID, +1); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
				return overlayOutcome{refresh: true}, nil
			case key == 'p' || key == 'P':
				if pane, ok := stepWindow(ctx, backend, layout, sessionID, currentPaneID, -1); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
				return overlayOutcome{refresh: true}, nil
			case key >= '1' && key <= '9':
				if pane, ok := selectWindowByNumber(ctx, backend, layout, sessionID, int(key-'0')); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
				return overlayOutcome{refresh: true}, nil
			case key == '%':
				if pane, ok := splitCurrentPane(ctx, layout, sessionID, currentPaneID, sessionbackend.SplitHorizontal, cols, rows); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
				return overlayOutcome{refresh: true}, nil
			case key == '"':
				if pane, ok := splitCurrentPane(ctx, layout, sessionID, currentPaneID, sessionbackend.SplitVertical, cols, rows); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
				return overlayOutcome{refresh: true}, nil
			case key == 'o' || key == 'O':
				if next, ok := pickNextPaneInWindow(ctx, backend, layout, sessionID, currentPaneID); ok && next != currentPaneID {
					return overlayOutcome{switchPane: next}, nil
				}
				return overlayOutcome{refresh: true}, nil
			case key == 'x' || key == 'X':
				return closeCurrentPane(ctx, backend, layout, sessionID, currentPaneID), nil
			case key == '&':
				return closeCurrentWindow(ctx, backend, layout, sessionID, currentPaneID), nil
			}
		}
	}
}

// runWindowSwitcher opens an interactive window/pane tree picker (`Ctrl+b w`).
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
	selected := 0
	initialized := false
	defer func() { _ = writeOut([]byte("\x1b[?25h")) }()

	for {
		st, err := backend.Observe(ctx, sessionID)
		if err != nil || st.Status != sessionbackend.StatusAlive || len(st.Windows) == 0 {
			return overlayOutcome{exited: true}, nil
		}
		items := buildSwitcherRows(st, currentPaneID)
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

		if err := writeOut([]byte(renderSwitcherView(st, items, selected))); err != nil {
			return overlayOutcome{}, err
		}

		select {
		case <-ctx.Done():
			return overlayOutcome{detached: true}, nil
		case rerr := <-inErrCh:
			return overlayOutcome{}, rerr
		case chunk := <-inCh:
			cleaned := FilterAutoReplies(chunk)
			if len(cleaned) == 0 {
				continue
			}
			// Handle ANSI arrow keys (\x1b[A up, \x1b[B down) before single-byte keys.
			if len(cleaned) >= 3 && cleaned[0] == 0x1b && cleaned[1] == '[' {
				switch cleaned[2] {
				case 'A': // Up
					selected = (selected - 1 + len(items)) % len(items)
					continue
				case 'B': // Down
					selected = (selected + 1) % len(items)
					continue
				}
			}
			key := cleaned[0]
			switch {
			case key == 'q' || key == 'Q' || key == 0x1b || key == 0x03:
				return overlayOutcome{refresh: true}, nil
			case key == 'j' || key == 'J':
				selected = (selected + 1) % len(items)
			case key == 'k' || key == 'K':
				selected = (selected - 1 + len(items)) % len(items)
			case key == '\r' || key == '\n':
				it := items[selected]
				if layout != nil {
					_ = layout.SelectWindow(ctx, sessionID, it.windowID)
					if it.paneID != "" {
						_, _ = layout.FocusPane(ctx, sessionID, it.windowID, it.paneID)
					}
				}
				return overlayOutcome{switchPane: it.paneID}, nil
			case key >= '1' && key <= '9':
				if pane, ok := selectWindowByNumber(ctx, backend, layout, sessionID, int(key-'0')); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
			case key == 'c' || key == 'C':
				if pane, ok := createAndSelectWindow(ctx, layout, sessionID, cols, rows); ok {
					return overlayOutcome{switchPane: pane}, nil
				}
			case key == '%':
				it := items[selected]
				if pane, ok := splitCurrentPane(ctx, layout, sessionID, it.paneID, sessionbackend.SplitHorizontal, cols, rows); ok {
					if layout != nil {
						_ = layout.SelectWindow(ctx, sessionID, it.windowID)
					}
					return overlayOutcome{switchPane: pane}, nil
				}
			case key == '"':
				it := items[selected]
				if pane, ok := splitCurrentPane(ctx, layout, sessionID, it.paneID, sessionbackend.SplitVertical, cols, rows); ok {
					if layout != nil {
						_ = layout.SelectWindow(ctx, sessionID, it.windowID)
					}
					return overlayOutcome{switchPane: pane}, nil
				}
			case key == 'x' || key == 'X':
				if layout != nil {
					it := items[selected]
					if it.isWindow {
						_ = layout.CloseWindow(ctx, sessionID, it.windowID)
					} else {
						_, _ = layout.ClosePane(ctx, sessionID, it.paneID)
					}
				}
			case key == 'm' || key == 'M':
				return runCommandMenu(ctx, backend, layout, sessionID, currentPaneID, inCh, inErrCh, writeOut, cols, rows)
			case key == 'd' || key == 'D':
				return overlayOutcome{detached: true}, nil
			}
		}
	}
}

func buildSwitcherRows(st sessionbackend.SessionState, currentPaneID string) []switcherRow {
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
					isWindow:    false,
					isActiveWin: isActiveWin,
					isActiveP:   pid == currentPaneID,
				})
			}
		}
	}
	return rows
}

func renderSwitcherView(st sessionbackend.SessionState, items []switcherRow, selected int) string {
	label := st.Label
	if label == "" {
		label = st.SessionID
	}
	var b strings.Builder
	b.WriteString(resetScrollRegion)
	b.WriteString("\x1b[2J\x1b[H\x1b[?25l")
	fmt.Fprintf(&b, "\x1b[1;36m=== 切换窗口 / 窗格 [%s] ===\x1b[0m\r\n", label)
	b.WriteString("\x1b[2m↑/↓(或 j/k) 选择  Enter 进入  1-9 直达窗口  c 新建窗口  %/\" 分屏  x 关闭  m 菜单  Esc 返回\x1b[0m\r\n\r\n")
	for i, it := range items {
		prefix := "  "
		if i == selected {
			prefix = "\x1b[1;30;46m> "
		}
		if it.isWindow {
			tag := ""
			if it.isActiveWin {
				tag = " [当前窗口]"
			}
			fmt.Fprintf(&b, "%s[%d] %s (%s)  窗格:%s%s", prefix, it.windowIndex, it.windowName, it.windowID, it.paneID, tag)
		} else {
			tag := ""
			if it.isActiveP {
				tag = " *"
			}
			fmt.Fprintf(&b, "%s    └─ 窗格 %s%s", prefix, it.paneID, tag)
		}
		if i == selected {
			b.WriteString(" \x1b[0m")
		}
		b.WriteString("\r\n")
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
