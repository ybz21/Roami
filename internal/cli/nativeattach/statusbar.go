package nativeattach

import (
	"bytes"
	"fmt"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/ybz21/Roami/internal/sessionbackend"
)

const (
	resetScrollRegion = "\x1b[r"
	saveCursorANSI    = "\x1b7"
	restoreCursorANSI = "\x1b8"
)

// statusBarInfo holds the snapshot rendered onto the reserved bottom terminal row.
type statusBarInfo struct {
	SessionLabel   string
	Windows        []sessionbackend.Window
	ActiveWindowID string
	ActivePaneID   string
	PrefixPending  bool
}

// applyScrollRegion bounds pane scrolling to rows 1..paneRows so output never scrolls over the status row.
func applyScrollRegion(paneRows uint16) string {
	if paneRows < 1 {
		return resetScrollRegion
	}
	return fmt.Sprintf("\x1b[1;%dr", paneRows)
}

// formatStatusBarText builds a single-line status bar clipped cleanly to cols display cells.
func formatStatusBarText(info statusBarInfo, cols uint16) string {
	w := int(cols)
	if w < 10 {
		w = 10
	}
	if info.PrefixPending {
		msg := ` [Ctrl+b] m:菜单 w:选窗口 c:新窗口 n/p:切窗口 1-9:窗口 %:左右 ":上下 o:切窗格 x:关窗格 &:关窗口 d:脱离`
		return padOrClipDisplay(msg, w)
	}

	label := info.SessionLabel
	if label == "" {
		label = "session"
	}
	var left strings.Builder
	left.WriteString(" [")
	left.WriteString(label)
	left.WriteString("]")

	paneHint := ""
	for i, win := range info.Windows {
		name := win.Name
		if name == "" {
			name = win.ID
		}
		mark := ""
		if win.ID == info.ActiveWindowID {
			mark = "*"
			if win.Layout != nil {
				panes := win.Layout.PaneIDs()
				if len(panes) > 1 {
					idx := 1
					for pi, pid := range panes {
						if pid == info.ActivePaneID {
							idx = pi + 1
							break
						}
					}
					paneHint = fmt.Sprintf(" %d/%d窗格", idx, len(panes))
				}
			}
		}
		fmt.Fprintf(&left, " %d:%s%s", i+1, name, mark)
	}
	if paneHint != "" {
		left.WriteString(" |")
		left.WriteString(paneHint)
	}

	right := `Ctrl+b m:菜单 w:窗口 c:新窗口 %/":分屏 d:脱离 `
	leftStr := left.String()
	leftW := displayWidth(leftStr)
	rightW := displayWidth(right)

	if leftW+rightW+2 <= w {
		return leftStr + strings.Repeat(" ", w-leftW-rightW) + right
	}
	// Narrow terminal: use compact hint so window tabs remain visible.
	shortRight := "Ctrl+b m:菜单 w:窗口 d:脱离 "
	shortRightW := displayWidth(shortRight)
	if leftW+shortRightW+2 <= w {
		return leftStr + strings.Repeat(" ", w-leftW-shortRightW) + shortRight
	}
	if w > shortRightW+6 {
		clippedLeft := clipDisplay(leftStr, w-shortRightW-1)
		gap := w - displayWidth(clippedLeft) - shortRightW
		if gap < 1 {
			gap = 1
		}
		return clippedLeft + strings.Repeat(" ", gap) + shortRight
	}
	return padOrClipDisplay(leftStr, w)
}

// renderStatusBarSequence emits an ANSI sequence that draws the bottom row without moving the pane cursor.
func renderStatusBarSequence(info statusBarInfo, cols, termRows uint16) []byte {
	if termRows < 2 || cols == 0 {
		return nil
	}
	line := formatStatusBarText(info, cols)
	style := "\x1b[0;30;46m" // black on cyan
	if info.PrefixPending {
		style = "\x1b[0;30;43m" // black on yellow when awaiting prefix command
	}
	var b strings.Builder
	b.WriteString(saveCursorANSI)
	fmt.Fprintf(&b, "\x1b[%d;1H%s%s\x1b[0m", termRows, style, line)
	b.WriteString(restoreCursorANSI)
	return []byte(b.String())
}

// outputMayResetStatusBar reports whether raw VT output might have cleared the status row or scroll region.
func outputMayResetStatusBar(data []byte) bool {
	return bytes.Contains(data, []byte("\x1b[2J")) ||
		bytes.Contains(data, []byte("\x1b[3J")) ||
		bytes.Contains(data, []byte("\x1b[?1049")) ||
		bytes.Contains(data, []byte("\x1b[r")) ||
		bytes.Contains(data, []byte("\x1bc"))
}

func displayWidth(s string) int {
	n := 0
	for _, r := range s {
		n += runeDisplayWidth(r)
	}
	return n
}

func runeDisplayWidth(r rune) int {
	if r < 0x20 || r == 0x7f {
		return 0
	}
	if unicode.Is(unicode.Han, r) ||
		unicode.Is(unicode.Hiragana, r) ||
		unicode.Is(unicode.Katakana, r) ||
		unicode.Is(unicode.Hangul, r) ||
		(r >= 0xff01 && r <= 0xff60) ||
		(r >= 0xffe0 && r <= 0xffe6) ||
		(r >= 0x3000 && r <= 0x303f) {
		return 2
	}
	return 1
}

func clipDisplay(s string, maxWidth int) string {
	if maxWidth <= 0 {
		return ""
	}
	if displayWidth(s) <= maxWidth {
		return s
	}
	var b strings.Builder
	used := 0
	for len(s) > 0 {
		r, sz := utf8.DecodeRuneInString(s)
		rw := runeDisplayWidth(r)
		if used+rw > maxWidth {
			break
		}
		b.WriteRune(r)
		used += rw
		s = s[sz:]
	}
	return b.String()
}

func padOrClipDisplay(s string, width int) string {
	clipped := clipDisplay(s, width)
	if pad := width - displayWidth(clipped); pad > 0 {
		return clipped + strings.Repeat(" ", pad)
	}
	return clipped
}
