// Pane & window structured API: supports both native roami-sessiond sessions and legacy tmux
// sessions so Web UI actions call real backend APIs instead of injecting raw Ctrl-b keystrokes.
package api

import (
	"context"
	"math"
	"net/http"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/sessionbackend"
)

var (
	paneIDPattern       = regexp.MustCompile(`^%\d+$`)
	nativePaneIDPattern = regexp.MustCompile(`^p-\d+$`)
)

// tmuxBinary 同 worktree.tmuxBin()：TMUX_BIN 可指向一个转发到隔离 socket 的 wrapper 脚本，
// 测试借此在真实 tmux 上跑，不会碰到用户自己的 tmux server。生产环境不设该变量，行为不变。
func tmuxBinary() string {
	if b := os.Getenv("TMUX_BIN"); b != "" {
		return b
	}
	return "tmux"
}

type paneInfo struct {
	PaneID        string `json:"paneId"`
	Left          int    `json:"left"`
	Top           int    `json:"top"`
	Width         int    `json:"width"`
	Height        int    `json:"height"`
	Cwd           string `json:"cwd"`
	Cmd           string `json:"cmd"`
	PanesInWindow int    `json:"panesInWindow"`
}

type windowSummary struct {
	ID     string `json:"id"`
	Index  int    `json:"index"`
	Name   string `json:"name"`
	Active bool   `json:"active"`
	Panes  int    `json:"panes"`
}

type sessionWindowsReply struct {
	Backend        string          `json:"backend"`
	ActiveWindowID string          `json:"activeWindowId"`
	ActivePaneID   string          `json:"activePaneId"`
	PanesInWindow  int             `json:"panesInWindow"`
	Windows        []windowSummary `json:"windows"`
}

const listPanesFormat = "#{pane_id}\t#{pane_active}\t#{pane_left}\t#{pane_top}\t#{pane_width}\t#{pane_height}\t#{pane_current_path}\t#{pane_current_command}\t#{window_id}"

// parsePanes 解析 listPanesFormat 的输出：只留活动 pane 所在窗口的那一组，panesInWindow 就是这一组的长度，
// 供前端判断「关了会不会连窗口一起没」。纯函数、不碰子进程，方便直接灌固定文本测试。
func parsePanes(raw string) ([]paneInfo, string) {
	type row struct {
		info   paneInfo
		window string
		active bool
	}
	var rows []row
	for _, line := range strings.Split(strings.TrimSpace(raw), "\n") {
		if line == "" {
			continue
		}
		parts := strings.Split(line, "\t")
		if len(parts) != 9 {
			continue
		}
		left, e1 := strconv.Atoi(parts[2])
		top, e2 := strconv.Atoi(parts[3])
		width, e3 := strconv.Atoi(parts[4])
		height, e4 := strconv.Atoi(parts[5])
		if e1 != nil || e2 != nil || e3 != nil || e4 != nil {
			continue
		}
		rows = append(rows, row{
			info: paneInfo{
				PaneID: parts[0], Left: left, Top: top, Width: width, Height: height,
				Cwd: parts[6], Cmd: parts[7],
			},
			window: parts[8],
			active: parts[1] == "1",
		})
	}
	var activeWindow string
	for _, r := range rows {
		if r.active {
			activeWindow = r.window
			break
		}
	}
	count := 0
	for _, r := range rows {
		if r.window == activeWindow {
			count++
		}
	}
	var out []paneInfo
	for _, r := range rows {
		if activeWindow == "" || r.window == activeWindow {
			p := r.info
			p.PanesInWindow = count
			out = append(out, p)
		}
	}
	return out, activeWindow
}

func listPanes(name string) ([]paneInfo, string) {
	out, err := exec.Command(tmuxBinary(), "list-panes", "-t", name, "-F", listPanesFormat).Output()
	if err != nil {
		return nil, ""
	}
	return parsePanes(string(out))
}

func nativeActiveWindow(st sessionbackend.SessionState) *sessionbackend.Window {
	for i := range st.Windows {
		if st.Windows[i].ID == st.ActiveWindowID {
			return &st.Windows[i]
		}
	}
	if len(st.Windows) > 0 {
		return &st.Windows[0]
	}
	return nil
}

func buildNativeWindowsReply(st sessionbackend.SessionState) sessionWindowsReply {
	reply := sessionWindowsReply{
		Backend:        string(sessionbackend.BackendNative),
		ActiveWindowID: st.ActiveWindowID,
		ActivePaneID:   st.ActivePaneID,
		Windows:        make([]windowSummary, 0, len(st.Windows)),
	}
	for i, w := range st.Windows {
		panes := 1
		if w.Layout != nil {
			panes = len(w.Layout.PaneIDs())
		}
		active := w.ID == st.ActiveWindowID
		if active {
			reply.PanesInWindow = panes
		}
		name := w.Name
		if name == "" {
			name = w.ID
		}
		reply.Windows = append(reply.Windows, windowSummary{
			ID:     w.ID,
			Index:  i + 1,
			Name:   name,
			Active: active,
			Panes:  panes,
		})
	}
	return reply
}

// ActivePane GET /sessions/:name/panes/active —— 当前活动 pane 的几何 + cwd + 前台进程。
func (a *API) ActivePane(c *gin.Context) {
	rawName := c.Param("name")
	if st, ok := a.nativeSession(c.Request.Context(), rawName); ok {
		win := nativeActiveWindow(st)
		if win == nil || st.ActivePaneID == "" {
			c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "PANE_NOT_FOUND"}})
			return
		}
		panesInWin := 1
		if win.Layout != nil {
			panesInWin = len(win.Layout.PaneIDs())
		}
		// Return approximate cell rect scaled to a 100x30 viewport so the confirmation highlight renders cleanly.
		left, top, width, height := 0, 0, 100, 30
		for _, r := range win.ComputeRects() {
			if r.PaneID == st.ActivePaneID {
				left = int(math.Round(r.X * 100))
				top = int(math.Round(r.Y * 30))
				width = max(1, int(math.Round(r.W*100)))
				height = max(1, int(math.Round(r.H*30)))
				break
			}
		}
		c.JSON(http.StatusOK, gin.H{"data": paneInfo{
			PaneID:        st.ActivePaneID,
			Left:          left,
			Top:           top,
			Width:         width,
			Height:        height,
			Cwd:           st.Cwd,
			Cmd:           "shell",
			PanesInWindow: panesInWin,
		}})
		return
	}

	name := a.sessionTarget(c)
	out, err := exec.Command(tmuxBinary(), "display-message", "-t", "="+name+":", "-p", "#{pane_id}").Output()
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "SESSION_NOT_FOUND"}})
		return
	}
	activeID := strings.TrimSpace(string(out))
	panes, _ := listPanes(name)
	for _, p := range panes {
		if p.PaneID == activeID {
			c.JSON(http.StatusOK, gin.H{"data": p})
			return
		}
	}
	c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "PANE_NOT_FOUND"}})
}

// ClosePane POST /sessions/:name/panes/:paneId/close —— 结构化关闭指定 pane。
func (a *API) ClosePane(c *gin.Context) {
	rawName := c.Param("name")
	paneID := c.Param("paneId")
	if _, ok := a.nativeSession(c.Request.Context(), rawName); ok {
		if !nativePaneIDPattern.MatchString(paneID) {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PANE_ID"}})
			return
		}
		lb, ok := a.NativeBackend.(sessionbackend.LayoutBackend)
		if !ok {
			c.JSON(http.StatusNotImplemented, gin.H{"error": gin.H{"code": "UNSUPPORTED"}})
			return
		}
		ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
		defer cancel()
		if _, err := lb.ClosePane(ctx, rawName, paneID); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "KILL_PANE_FAILED", "message": err.Error()}})
			return
		}
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"closed": paneID}})
		return
	}

	name := a.sessionTarget(c)
	if !paneIDPattern.MatchString(paneID) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PANE_ID"}})
		return
	}
	if out, err := exec.Command(tmuxBinary(), "kill-pane", "-t", paneID).CombinedOutput(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "KILL_PANE_FAILED", "message": strings.TrimSpace(string(out))}})
		return
	}
	panes, _ := listPanes(name)
	for _, p := range panes {
		if p.PaneID == paneID {
			c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": "PANE_STILL_ALIVE"}})
			return
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"closed": paneID}})
}

// SessionWindows GET /sessions/:name/windows —— 返回会话的窗口列表与活跃窗格摘要（原生 + tmux 统一）。
func (a *API) SessionWindows(c *gin.Context) {
	rawName := c.Param("name")
	if st, ok := a.nativeSession(c.Request.Context(), rawName); ok {
		c.JSON(http.StatusOK, gin.H{"data": buildNativeWindowsReply(st)})
		return
	}
	name := a.sessionTarget(c)
	reply, err := listTmuxWindows(name)
	if err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": gin.H{"code": "SESSION_NOT_FOUND", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": reply})
}

func listTmuxWindows(name string) (sessionWindowsReply, error) {
	out, err := exec.Command(tmuxBinary(), "list-windows", "-t", "="+name, "-F", "#{window_id}\t#{window_index}\t#{window_name}\t#{window_active}\t#{window_panes}").Output()
	if err != nil {
		return sessionWindowsReply{}, err
	}
	reply := sessionWindowsReply{Backend: string(sessionbackend.BackendTmux)}
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		if line == "" {
			continue
		}
		parts := strings.Split(line, "\t")
		if len(parts) < 5 {
			continue
		}
		idx, _ := strconv.Atoi(parts[1])
		panes, _ := strconv.Atoi(parts[4])
		active := parts[3] == "1"
		if active {
			reply.ActiveWindowID = parts[0]
			reply.PanesInWindow = panes
		}
		reply.Windows = append(reply.Windows, windowSummary{
			ID:     parts[0],
			Index:  idx,
			Name:   parts[2],
			Active: active,
			Panes:  panes,
		})
	}
	if activePane, err := exec.Command(tmuxBinary(), "display-message", "-t", "="+name+":", "-p", "#{pane_id}").Output(); err == nil {
		reply.ActivePaneID = strings.TrimSpace(string(activePane))
	}
	return reply, nil
}

// SessionTerminalAction POST /sessions/:name/terminal-action —— 结构化执行分屏/窗格/窗口动作，
// 取代前端直接向 PTY 注入 Ctrl+b 原始字节的做法，同时兼容原生宿主和 tmux 会话。
func (a *API) SessionTerminalAction(c *gin.Context) {
	rawName := c.Param("name")
	var req struct {
		Action    string `json:"action"`
		Direction string `json:"direction"`
		WindowID  string `json:"windowId"`
		PaneID    string `json:"paneId"`
	}
	if err := c.ShouldBindJSON(&req); err != nil || strings.TrimSpace(req.Action) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST", "message": "action required"}})
		return
	}

	if st, ok := a.nativeSession(c.Request.Context(), rawName); ok {
		a.runNativeTerminalAction(c, rawName, st, req.Action, req.Direction, req.WindowID, req.PaneID)
		return
	}
	name := a.sessionTarget(c)
	a.runTmuxTerminalAction(c, name, req.Action, req.Direction, req.WindowID)
}

func (a *API) runNativeTerminalAction(c *gin.Context, name string, st sessionbackend.SessionState, action, direction, windowID, paneID string) {
	lb, ok := a.NativeBackend.(sessionbackend.LayoutBackend)
	if !ok {
		c.JSON(http.StatusNotImplemented, gin.H{"error": gin.H{"code": "UNSUPPORTED"}})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()

	targetPane := paneID
	if targetPane == "" {
		targetPane = st.ActivePaneID
	}
	win := nativeActiveWindow(st)

	var err error
	switch action {
	case "split-right":
		_, _, err = lb.SplitPane(ctx, name, targetPane, sessionbackend.SplitSpec{Dir: sessionbackend.SplitHorizontal, LoginShell: true})
	case "split-down":
		_, _, err = lb.SplitPane(ctx, name, targetPane, sessionbackend.SplitSpec{Dir: sessionbackend.SplitVertical, LoginShell: true})
	case "next-pane":
		if win != nil && win.Layout != nil {
			panes := win.Layout.PaneIDs()
			if len(panes) > 1 {
				next := panes[0]
				for i, pid := range panes {
					if pid == targetPane {
						next = panes[(i+1)%len(panes)]
						break
					}
				}
				_, err = lb.FocusPane(ctx, name, win.ID, next)
			}
		}
	case "focus-pane":
		var dir sessionbackend.FocusDir
		switch direction {
		case "up":
			dir = sessionbackend.FocusUp
		case "down":
			dir = sessionbackend.FocusDown
		case "left":
			dir = sessionbackend.FocusLeft
		case "right":
			dir = sessionbackend.FocusRight
		default:
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_DIRECTION"}})
			return
		}
		if win != nil {
			if nb, found := win.FindNeighbor(targetPane, dir); found {
				_, err = lb.FocusPane(ctx, name, win.ID, nb)
			}
		}
	case "new-window":
		_, err = lb.NewWindow(ctx, name, sessionbackend.WindowSpec{LoginShell: true})
	case "next-window", "prev-window":
		if len(st.Windows) > 1 {
			cur := 0
			for i, w := range st.Windows {
				if w.ID == st.ActiveWindowID {
					cur = i
					break
				}
			}
			delta := 1
			if action == "prev-window" {
				delta = -1
			}
			next := st.Windows[(cur+delta+len(st.Windows))%len(st.Windows)]
			err = lb.SelectWindow(ctx, name, next.ID)
		}
	case "select-window":
		if windowID == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "WINDOW_ID_REQUIRED"}})
			return
		}
		err = lb.SelectWindow(ctx, name, windowID)
	case "close-window":
		targetWin := windowID
		if targetWin == "" {
			targetWin = st.ActiveWindowID
		}
		err = lb.CloseWindow(ctx, name, targetWin)
	default:
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "UNKNOWN_ACTION", "message": action}})
		return
	}
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "ACTION_FAILED", "message": err.Error()}})
		return
	}
	if updated, ok := a.nativeSession(c.Request.Context(), name); ok {
		c.JSON(http.StatusOK, gin.H{"data": buildNativeWindowsReply(updated)})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

func (a *API) runTmuxTerminalAction(c *gin.Context, name, action, direction, windowID string) {
	var args []string
	switch action {
	case "split-right":
		args = []string{"split-window", "-h", "-t", "=" + name + ":"}
	case "split-down":
		args = []string{"split-window", "-v", "-t", "=" + name + ":"}
	case "next-pane":
		args = []string{"select-pane", "-t", "=" + name + ":.+"}
	case "focus-pane":
		flag := ""
		switch direction {
		case "up":
			flag = "-U"
		case "down":
			flag = "-D"
		case "left":
			flag = "-L"
		case "right":
			flag = "-R"
		default:
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_DIRECTION"}})
			return
		}
		args = []string{"select-pane", flag, "-t", "=" + name + ":"}
	case "new-window":
		args = []string{"new-window", "-t", "=" + name + ":"}
	case "next-window":
		args = []string{"next-window", "-t", "=" + name}
	case "prev-window":
		args = []string{"previous-window", "-t", "=" + name}
	case "select-window":
		if windowID == "" {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "WINDOW_ID_REQUIRED"}})
			return
		}
		args = []string{"select-window", "-t", "=" + name + ":" + windowID}
	case "close-window":
		target := "=" + name + ":"
		if windowID != "" {
			target = "=" + name + ":" + windowID
		}
		args = []string{"kill-window", "-t", target}
	default:
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "UNKNOWN_ACTION", "message": action}})
		return
	}
	if out, err := exec.Command(tmuxBinary(), args...).CombinedOutput(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "ACTION_FAILED", "message": strings.TrimSpace(string(out))}})
		return
	}
	if reply, err := listTmuxWindows(name); err == nil {
		c.JSON(http.StatusOK, gin.H{"data": reply})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}
