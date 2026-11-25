package sessionhost

import (
	"bytes"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/ybz21/Roami/internal/sessionbackend"
)

const DefaultScrollback = 5000

type vtCell struct {
	ch    rune
	width uint8 // 1 normal, 2 wide lead, 0 wide trail
	dim   bool
	gray  bool
	bold  bool
	inv   bool
	fg    string // raw SGR fg fragment, empty = default
	bg    string // raw SGR bg fragment, empty = default
}

type vtScreen struct {
	cols, rows int
	grid       [][]vtCell
	scrollback [][]vtCell
	maxScroll  int
	cx, cy     int
	savedX     int
	savedY     int
	scrollTop  int
	scrollBot  int
}

func newVTScreen(cols, rows, maxScroll int) *vtScreen {
	s := &vtScreen{
		cols:      cols,
		rows:      rows,
		maxScroll: maxScroll,
		scrollTop: 0,
		scrollBot: rows - 1,
	}
	s.grid = makeGrid(cols, rows)
	return s
}

func makeRow(cols int) []vtCell {
	row := make([]vtCell, cols)
	for i := range row {
		row[i] = vtCell{ch: ' ', width: 1}
	}
	return row
}

func makeGrid(cols, rows int) [][]vtCell {
	g := make([][]vtCell, rows)
	for y := 0; y < rows; y++ {
		g[y] = makeRow(cols)
	}
	return g
}

func (s *vtScreen) resize(cols, rows int) {
	if cols < 1 {
		cols = 1
	}
	if rows < 1 {
		rows = 1
	}
	next := makeGrid(cols, rows)
	copyRows := rows
	if len(s.grid) < copyRows {
		copyRows = len(s.grid)
	}
	for y := 0; y < copyRows; y++ {
		copyCols := cols
		if len(s.grid[y]) < copyCols {
			copyCols = len(s.grid[y])
		}
		copy(next[y][:copyCols], s.grid[y][:copyCols])
	}
	s.grid = next
	s.cols, s.rows = cols, rows
	s.scrollTop, s.scrollBot = 0, rows-1
	if s.cx >= cols {
		s.cx = cols - 1
	}
	if s.cy >= rows {
		s.cy = rows - 1
	}
}

func (s *vtScreen) scrollUp(n int, keepHistory bool) {
	if n <= 0 {
		return
	}
	top, bot := s.scrollTop, s.scrollBot
	if top < 0 {
		top = 0
	}
	if bot >= s.rows {
		bot = s.rows - 1
	}
	if top > bot {
		return
	}
	for k := 0; k < n; k++ {
		if keepHistory && top == 0 && s.maxScroll > 0 {
			saved := make([]vtCell, len(s.grid[top]))
			copy(saved, s.grid[top])
			s.scrollback = append(s.scrollback, saved)
			if len(s.scrollback) > s.maxScroll {
				s.scrollback = s.scrollback[len(s.scrollback)-s.maxScroll:]
			}
		}
		for y := top; y < bot; y++ {
			s.grid[y] = s.grid[y+1]
		}
		s.grid[bot] = makeRow(s.cols)
	}
}

func (s *vtScreen) scrollDown(n int) {
	top, bot := s.scrollTop, s.scrollBot
	if top < 0 || bot >= s.rows || top > bot {
		return
	}
	for k := 0; k < n; k++ {
		for y := bot; y > top; y-- {
			s.grid[y] = s.grid[y-1]
		}
		s.grid[top] = makeRow(s.cols)
	}
}

type vtParseState uint8

const (
	vtGround vtParseState = iota
	vtEsc
	vtCSI
	vtOSC
	vtOSCEsc
	vtCharset
)

// Emulator is a server-side VT100/xterm terminal state machine that tracks normal/alt screens,
// scrollback, SGR dim/gray attributes, DEC private modes, OSC 7 cwd, and answers DA/DSR queries.
type Emulator struct {
	normal *vtScreen
	alt    *vtScreen
	cur    *vtScreen

	altOn          bool
	mouseOn        bool
	mouseSGR       bool
	decckm         bool
	bracketedPaste bool
	cwd            string

	// Current pen style.
	dim  bool
	gray bool
	bold bool
	inv  bool
	fg   string
	bg   string

	// Incremental parser state (handles UTF-8 and escape sequences split across reads).
	state   vtParseState
	utf8Buf []byte
	csiBuf  []byte
	oscBuf  []byte
}

func NewEmulator(cols, rows uint16, maxScrollback int) *Emulator {
	if cols == 0 {
		cols = 100
	}
	if rows == 0 {
		rows = 30
	}
	if maxScrollback <= 0 {
		maxScrollback = DefaultScrollback
	}
	norm := newVTScreen(int(cols), int(rows), maxScrollback)
	alt := newVTScreen(int(cols), int(rows), 0)
	return &Emulator{
		normal: norm,
		alt:    alt,
		cur:    norm,
	}
}

func (e *Emulator) Mode() sessionbackend.TerminalMode {
	return sessionbackend.TerminalMode{
		AltScreen:      e.altOn,
		MouseOn:        e.mouseOn,
		MouseSGR:       e.mouseSGR,
		DECCKM:         e.decckm,
		BracketedPaste: e.bracketedPaste,
		CursorX:        e.cur.cx,
		CursorY:        e.cur.cy,
		Cols:           uint16(e.cur.cols),
		Rows:           uint16(e.cur.rows),
	}
}

func (e *Emulator) Cwd() string { return e.cwd }

func (e *Emulator) Resize(cols, rows uint16) {
	if cols < 1 || rows < 1 {
		return
	}
	e.normal.resize(int(cols), int(rows))
	e.alt.resize(int(cols), int(rows))
}

// Feed processes raw PTY output bytes, updating screen state and returning any terminal query replies
// (DA1/DA2/DSR) that the host should immediately write back to the PTY.
func (e *Emulator) Feed(data []byte) (replies [][]byte, modeChanged bool) {
	before := e.Mode()
	for i := 0; i < len(data); i++ {
		b := data[i]
		switch e.state {
		case vtGround:
			if len(e.utf8Buf) > 0 {
				if b&0xc0 == 0x80 {
					e.utf8Buf = append(e.utf8Buf, b)
					if utf8.FullRune(e.utf8Buf) {
						r, _ := utf8.DecodeRune(e.utf8Buf)
						e.utf8Buf = e.utf8Buf[:0]
						e.putRune(r)
					}
					continue
				}
				e.utf8Buf = e.utf8Buf[:0]
			}
			if b >= 0x80 {
				e.utf8Buf = append(e.utf8Buf[:0], b)
				if utf8.FullRune(e.utf8Buf) {
					r, _ := utf8.DecodeRune(e.utf8Buf)
					e.utf8Buf = e.utf8Buf[:0]
					e.putRune(r)
				}
				continue
			}
			switch b {
			case 0x1b:
				e.state = vtEsc
			case '\r':
				e.cur.cx = 0
			case '\n', '\v', '\f':
				e.lineFeed()
			case '\b':
				if e.cur.cx > 0 {
					e.cur.cx--
				}
			case '\t':
				next := (e.cur.cx/8 + 1) * 8
				if next >= e.cur.cols {
					next = e.cur.cols - 1
				}
				e.cur.cx = next
			case 0x07, 0x00:
				// BEL / NUL ignored
			default:
				if b >= 0x20 {
					e.putRune(rune(b))
				}
			}
		case vtEsc:
			switch b {
			case '[':
				e.csiBuf = e.csiBuf[:0]
				e.state = vtCSI
			case ']':
				e.oscBuf = e.oscBuf[:0]
				e.state = vtOSC
			case '(', ')', '*', '+':
				e.state = vtCharset
			case '7':
				e.cur.savedX, e.cur.savedY = e.cur.cx, e.cur.cy
				e.state = vtGround
			case '8':
				e.cur.cx, e.cur.cy = clampInt(e.cur.savedX, 0, e.cur.cols-1), clampInt(e.cur.savedY, 0, e.cur.rows-1)
				e.state = vtGround
			case 'M': // Reverse index
				if e.cur.cy == e.cur.scrollTop {
					e.cur.scrollDown(1)
				} else if e.cur.cy > 0 {
					e.cur.cy--
				}
				e.state = vtGround
			case 'D': // Index
				e.lineFeed()
				e.state = vtGround
			case 'c': // RIS full reset
				e.reset()
				e.state = vtGround
			default:
				e.state = vtGround
			}
		case vtCharset:
			e.state = vtGround
		case vtCSI:
			if b >= 0x40 && b <= 0x7e {
				if reply := e.execCSI(string(e.csiBuf), b); len(reply) > 0 {
					replies = append(replies, reply)
				}
				e.state = vtGround
			} else if len(e.csiBuf) < 256 {
				e.csiBuf = append(e.csiBuf, b)
			} else {
				e.state = vtGround
			}
		case vtOSC:
			if b == 0x07 {
				e.execOSC(string(e.oscBuf))
				e.state = vtGround
			} else if b == 0x1b {
				e.state = vtOSCEsc
			} else if len(e.oscBuf) < 4096 {
				e.oscBuf = append(e.oscBuf, b)
			} else {
				e.state = vtGround
			}
		case vtOSCEsc:
			if b == '\\' {
				e.execOSC(string(e.oscBuf))
			}
			e.state = vtGround
		}
	}
	after := e.Mode()
	modeChanged = before.AltScreen != after.AltScreen ||
		before.MouseOn != after.MouseOn ||
		before.MouseSGR != after.MouseSGR ||
		before.DECCKM != after.DECCKM ||
		before.BracketedPaste != after.BracketedPaste
	return replies, modeChanged
}

func (e *Emulator) reset() {
	cols, rows, maxScroll := e.normal.cols, e.normal.rows, e.normal.maxScroll
	e.normal = newVTScreen(cols, rows, maxScroll)
	e.alt = newVTScreen(cols, rows, 0)
	e.cur = e.normal
	e.altOn, e.mouseOn, e.mouseSGR, e.decckm, e.bracketedPaste = false, false, false, false, false
	e.dim, e.gray, e.bold, e.inv, e.fg, e.bg = false, false, false, false, "", ""
}

func (e *Emulator) lineFeed() {
	if e.cur.cy == e.cur.scrollBot {
		e.cur.scrollUp(1, !e.altOn)
		return
	}
	if e.cur.cy < e.cur.rows-1 {
		e.cur.cy++
	}
}

func (e *Emulator) putRune(r rune) {
	w := runeCellWidth(r)
	if w == 0 {
		return
	}
	if e.cur.cx+w > e.cur.cols {
		e.cur.cx = 0
		e.lineFeed()
	}
	if e.cur.cy >= 0 && e.cur.cy < e.cur.rows && e.cur.cx >= 0 && e.cur.cx < e.cur.cols {
		e.cur.grid[e.cur.cy][e.cur.cx] = vtCell{
			ch: r, width: uint8(w), dim: e.dim, gray: e.gray, bold: e.bold, inv: e.inv, fg: e.fg, bg: e.bg,
		}
		if w == 2 && e.cur.cx+1 < e.cur.cols {
			e.cur.grid[e.cur.cy][e.cur.cx+1] = vtCell{ch: 0, width: 0, dim: e.dim, gray: e.gray, bold: e.bold, inv: e.inv, fg: e.fg, bg: e.bg}
		}
	}
	e.cur.cx += w
	if e.cur.cx >= e.cur.cols {
		e.cur.cx = e.cur.cols - 1
	}
}

func (e *Emulator) execCSI(raw string, final byte) []byte {
	private := byte(0)
	if len(raw) > 0 && (raw[0] == '?' || raw[0] == '>') {
		private = raw[0]
		raw = raw[1:]
	}
	params := parseCSIParams(raw)
	arg := func(idx, def int) int {
		if idx < len(params) && params[idx] > 0 {
			return params[idx]
		}
		return def
	}

	if private == '?' {
		if final == 'h' || final == 'l' {
			on := final == 'h'
			for _, p := range params {
				switch p {
				case 1:
					e.decckm = on
				case 47, 1047, 1049:
					if on && !e.altOn {
						e.normal.savedX, e.normal.savedY = e.normal.cx, e.normal.cy
						e.alt = newVTScreen(e.normal.cols, e.normal.rows, 0)
						e.cur = e.alt
						e.altOn = true
					} else if !on && e.altOn {
						e.cur = e.normal
						e.altOn = false
						if p == 1049 {
							e.normal.cx = clampInt(e.normal.savedX, 0, e.normal.cols-1)
							e.normal.cy = clampInt(e.normal.savedY, 0, e.normal.rows-1)
						}
					}
				case 1000, 1001, 1002, 1003:
					e.mouseOn = on
				case 1006:
					e.mouseSGR = on
				case 2004:
					e.bracketedPaste = on
				}
			}
		}
		return nil
	}

	if private == '>' {
		if final == 'c' {
			return []byte("\x1b[>0;10;1c")
		}
		return nil
	}

	switch final {
	case 'c': // Primary DA1 query
		if len(params) == 0 || params[0] == 0 {
			return []byte("\x1b[?62;c")
		}
	case 'n': // DSR query (crucial for Windows ConPTY / PSReadLine ESC[6n)
		if len(params) > 0 && params[0] == 5 {
			return []byte("\x1b[0n")
		}
		if len(params) > 0 && params[0] == 6 {
			return []byte(fmt.Sprintf("\x1b[%d;%dR", e.cur.cy+1, e.cur.cx+1))
		}
	case 'A':
		e.cur.cy = clampInt(e.cur.cy-arg(0, 1), 0, e.cur.rows-1)
	case 'B':
		e.cur.cy = clampInt(e.cur.cy+arg(0, 1), 0, e.cur.rows-1)
	case 'C':
		e.cur.cx = clampInt(e.cur.cx+arg(0, 1), 0, e.cur.cols-1)
	case 'D':
		e.cur.cx = clampInt(e.cur.cx-arg(0, 1), 0, e.cur.cols-1)
	case 'G':
		e.cur.cx = clampInt(arg(0, 1)-1, 0, e.cur.cols-1)
	case 'd':
		e.cur.cy = clampInt(arg(0, 1)-1, 0, e.cur.rows-1)
	case 'H', 'f':
		e.cur.cy = clampInt(arg(0, 1)-1, 0, e.cur.rows-1)
		e.cur.cx = clampInt(arg(1, 1)-1, 0, e.cur.cols-1)
	case 'J':
		mode := 0
		if len(params) > 0 {
			mode = params[0]
		}
		switch mode {
		case 0:
			for x := e.cur.cx; x < e.cur.cols; x++ {
				e.cur.grid[e.cur.cy][x] = vtCell{ch: ' ', width: 1}
			}
			for y := e.cur.cy + 1; y < e.cur.rows; y++ {
				e.cur.grid[y] = makeRow(e.cur.cols)
			}
		case 1:
			for y := 0; y < e.cur.cy; y++ {
				e.cur.grid[y] = makeRow(e.cur.cols)
			}
			for x := 0; x <= e.cur.cx && x < e.cur.cols; x++ {
				e.cur.grid[e.cur.cy][x] = vtCell{ch: ' ', width: 1}
			}
		case 2, 3:
			for y := 0; y < e.cur.rows; y++ {
				e.cur.grid[y] = makeRow(e.cur.cols)
			}
			if mode == 3 {
				e.cur.scrollback = nil
			}
		}
	case 'K':
		mode := 0
		if len(params) > 0 {
			mode = params[0]
		}
		switch mode {
		case 0:
			for x := e.cur.cx; x < e.cur.cols; x++ {
				e.cur.grid[e.cur.cy][x] = vtCell{ch: ' ', width: 1}
			}
		case 1:
			for x := 0; x <= e.cur.cx && x < e.cur.cols; x++ {
				e.cur.grid[e.cur.cy][x] = vtCell{ch: ' ', width: 1}
			}
		case 2:
			e.cur.grid[e.cur.cy] = makeRow(e.cur.cols)
		}
	case 'S':
		e.cur.scrollUp(arg(0, 1), !e.altOn)
	case 'T':
		e.cur.scrollDown(arg(0, 1))
	case 'r':
		top := arg(0, 1) - 1
		bot := arg(1, e.cur.rows) - 1
		if top >= 0 && bot < e.cur.rows && top < bot {
			e.cur.scrollTop, e.cur.scrollBot = top, bot
		} else {
			e.cur.scrollTop, e.cur.scrollBot = 0, e.cur.rows-1
		}
		e.cur.cx, e.cur.cy = 0, 0
	case 's':
		e.cur.savedX, e.cur.savedY = e.cur.cx, e.cur.cy
	case 'u':
		e.cur.cx, e.cur.cy = clampInt(e.cur.savedX, 0, e.cur.cols-1), clampInt(e.cur.savedY, 0, e.cur.rows-1)
	case 'm':
		e.applySGR(params)
	}
	return nil
}

func (e *Emulator) applySGR(ps []int) {
	if len(ps) == 0 {
		e.dim, e.gray, e.bold, e.inv, e.fg, e.bg = false, false, false, false, "", ""
		return
	}
	for i := 0; i < len(ps); i++ {
		n := ps[i]
		switch {
		case n == 0:
			e.dim, e.gray, e.bold, e.inv, e.fg, e.bg = false, false, false, false, "", ""
		case n == 1:
			e.bold = true
		case n == 2:
			e.dim = true
		case n == 7:
			e.inv = true
		case n == 22:
			e.dim, e.bold = false, false
		case n == 27:
			e.inv = false
		case n == 39:
			e.fg, e.gray = "", false
		case n == 49:
			e.bg = ""
		case n == 90:
			e.fg, e.gray = "90", true
		case (n >= 30 && n <= 37) || (n >= 91 && n <= 97):
			e.fg, e.gray = strconv.Itoa(n), false
		case (n >= 40 && n <= 47) || (n >= 100 && n <= 107):
			e.bg = strconv.Itoa(n)
		case n == 38 && i+1 < len(ps):
			if ps[i+1] == 5 && i+2 < len(ps) {
				c := ps[i+2]
				e.fg = fmt.Sprintf("38;5;%d", c)
				e.gray = c == 8 || (c >= 232 && c <= 250)
				i += 2
			} else if ps[i+1] == 2 && i+4 < len(ps) {
				r, g, b := ps[i+2], ps[i+3], ps[i+4]
				e.fg = fmt.Sprintf("38;2;%d;%d;%d", r, g, b)
				e.gray = r == g && g == b && r <= 0xa0
				i += 4
			}
		case n == 48 && i+1 < len(ps):
			if ps[i+1] == 5 && i+2 < len(ps) {
				e.bg = fmt.Sprintf("48;5;%d", ps[i+2])
				i += 2
			} else if ps[i+1] == 2 && i+4 < len(ps) {
				e.bg = fmt.Sprintf("48;2;%d;%d;%d", ps[i+2], ps[i+3], ps[i+4])
				i += 4
			}
		}
	}
}

func (e *Emulator) execOSC(raw string) {
	code, val, ok := strings.Cut(raw, ";")
	if !ok {
		return
	}
	if code == "7" {
		if u, err := url.Parse(strings.TrimSpace(val)); err == nil && u.Scheme == "file" && u.Path != "" {
			e.cwd = u.Path
		}
	}
}

// LastRealCol returns the last column on row containing a non-dim, non-gray, non-space rune,
// matching backend/pty's Claude Code suggestion-guard semantics for move-cursor.
func (e *Emulator) LastRealCol(row int) int {
	if row < 0 || row >= e.cur.rows {
		return -1
	}
	last := -1
	line := e.cur.grid[row]
	for col := 0; col < len(line); col++ {
		c := line[col]
		if c.width == 0 || c.ch == 0 || c.ch == ' ' || c.dim || c.gray {
			continue
		}
		last = col + int(c.width) - 1
	}
	return last
}

// CaptureText returns trimmed plain text lines from the current screen (and optional scrollback).
func (e *Emulator) CaptureText(lines int, includeHistory bool) string {
	var all [][]vtCell
	if includeHistory && !e.altOn && len(e.normal.scrollback) > 0 {
		all = append(all, e.normal.scrollback...)
	}
	all = append(all, e.cur.grid...)
	out := make([]string, 0, len(all))
	for _, row := range all {
		out = append(out, rowPlainText(row))
	}
	// Trim trailing blank lines.
	for len(out) > 0 && out[len(out)-1] == "" {
		out = out[:len(out)-1]
	}
	if lines > 0 && len(out) > lines {
		out = out[len(out)-lines:]
	}
	return strings.Join(out, "\n")
}

// RenderRowFixed serializes exactly e.cur.cols display cells of rowIdx with ANSI styles
// and trailing spaces (no trailing newline or erase-to-EOL) for side-by-side pane compositing.
func (e *Emulator) RenderRowFixed(rowIdx int) string {
	if rowIdx < 0 || rowIdx >= e.cur.rows {
		return strings.Repeat(" ", e.cur.cols)
	}
	row := e.cur.grid[rowIdx]
	var b bytes.Buffer
	var lastStyle string
	written := 0
	for x := 0; x < len(row); x++ {
		c := row[x]
		if c.width == 0 {
			continue
		}
		w := int(c.width)
		if w == 0 {
			w = 1
		}
		if written+w > e.cur.cols {
			break
		}
		style := cellStyle(c)
		if style != lastStyle {
			if style == "" {
				b.WriteString("\x1b[0m")
			} else {
				b.WriteString("\x1b[0;")
				b.WriteString(style)
				b.WriteByte('m')
			}
			lastStyle = style
		}
		if c.ch == 0 {
			b.WriteByte(' ')
		} else {
			b.WriteRune(c.ch)
		}
		written += w
	}
	if lastStyle != "" {
		b.WriteString("\x1b[0m")
	}
	for written < e.cur.cols {
		b.WriteByte(' ')
		written++
	}
	return b.String()
}

// SnapshotANSI serializes scrollback + active screen + cursor + modes so a reconnecting
// xterm.js client reproduces the host terminal cleanly at an exact sequence boundary.
func (e *Emulator) SnapshotANSI() []byte {
	var b bytes.Buffer
	b.WriteString("\x1b[0m\x1b[?25h")
	if e.altOn {
		b.WriteString("\x1b[?1049h\x1b[2J\x1b[H")
		writeGridANSI(&b, e.alt.grid)
	} else {
		b.WriteString("\x1b[?1049l\x1b[2J\x1b[H")
		for _, row := range e.normal.scrollback {
			writeRowANSI(&b, row)
			b.WriteString("\r\n")
		}
		writeGridANSI(&b, e.normal.grid)
	}
	b.WriteString("\x1b[0m")
	if e.decckm {
		b.WriteString("\x1b[?1h")
	} else {
		b.WriteString("\x1b[?1l")
	}
	if e.bracketedPaste {
		b.WriteString("\x1b[?2004h")
	} else {
		b.WriteString("\x1b[?2004l")
	}
	fmt.Fprintf(&b, "\x1b[%d;%dH", e.cur.cy+1, e.cur.cx+1)
	return b.Bytes()
}

func writeGridANSI(b *bytes.Buffer, grid [][]vtCell) {
	for y, row := range grid {
		writeRowANSI(b, row)
		if y < len(grid)-1 {
			b.WriteString("\r\n")
		}
	}
}

func writeRowANSI(b *bytes.Buffer, row []vtCell) {
	end := len(row) - 1
	for end >= 0 && row[end].ch == ' ' && row[end].fg == "" && row[end].bg == "" && !row[end].inv {
		end--
	}
	var lastStyle string
	for x := 0; x <= end; x++ {
		c := row[x]
		if c.width == 0 {
			continue
		}
		style := cellStyle(c)
		if style != lastStyle {
			if style == "" {
				b.WriteString("\x1b[0m")
			} else {
				b.WriteString("\x1b[0;")
				b.WriteString(style)
				b.WriteByte('m')
			}
			lastStyle = style
		}
		if c.ch == 0 {
			b.WriteByte(' ')
		} else {
			b.WriteRune(c.ch)
		}
	}
	if lastStyle != "" {
		b.WriteString("\x1b[0m")
	}
}

func cellStyle(c vtCell) string {
	var parts []string
	if c.bold {
		parts = append(parts, "1")
	}
	if c.dim {
		parts = append(parts, "2")
	}
	if c.inv {
		parts = append(parts, "7")
	}
	if c.fg != "" {
		parts = append(parts, c.fg)
	}
	if c.bg != "" {
		parts = append(parts, c.bg)
	}
	return strings.Join(parts, ";")
}

func rowPlainText(row []vtCell) string {
	var b strings.Builder
	for _, c := range row {
		if c.width == 0 {
			continue
		}
		if c.ch == 0 {
			b.WriteByte(' ')
		} else {
			b.WriteRune(c.ch)
		}
	}
	return strings.TrimRight(b.String(), " ")
}

func parseCSIParams(raw string) []int {
	if raw == "" {
		return nil
	}
	parts := strings.Split(raw, ";")
	out := make([]int, 0, len(parts))
	for _, p := range parts {
		if p == "" {
			out = append(out, 0)
			continue
		}
		n, _ := strconv.Atoi(p)
		out = append(out, n)
	}
	return out
}

func clampInt(v, lo, hi int) int {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func runeCellWidth(r rune) int {
	switch {
	case r == 0:
		return 0
	case r < 0x300:
		return 1
	case r >= 0x300 && r <= 0x36f, r >= 0x200b && r <= 0x200f:
		return 0
	case r >= 0x1100 && r <= 0x115f, r >= 0x2e80 && r <= 0xa4cf, r >= 0xac00 && r <= 0xd7a3,
		r >= 0xf900 && r <= 0xfaff, r >= 0xfe30 && r <= 0xfe4f, r >= 0xff00 && r <= 0xff60,
		r >= 0xffe0 && r <= 0xffe6, r >= 0x1f300 && r <= 0x1f64f, r >= 0x1f900 && r <= 0x1f9ff,
		r >= 0x20000 && r <= 0x3fffd:
		return 2
	}
	return 1
}
