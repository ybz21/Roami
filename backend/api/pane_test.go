package api

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/sessionbackend"
	"github.com/ybz21/Roami/internal/sessionhost"
)

func TestParsePanesGroupsByActiveWindowOnly(t *testing.T) {
	// 两个窗口：window0 有 2 个 pane（第二个是 active），window1 有 1 个 pane。
	// 期望只返回 window0 那一组，panesInWindow=2。
	raw := strings.Join([]string{
		"%1\t0\t0\t0\t80\t24\t/home/a\tbash\t@0",
		"%2\t1\t80\t0\t80\t24\t/home/b\tvim\t@0",
		"%3\t0\t0\t0\t160\t24\t/home/c\tclaude\t@1",
	}, "\n")
	panes, window := parsePanes(raw)
	if window != "@0" {
		t.Fatalf("expected active window @0, got %q", window)
	}
	if len(panes) != 2 {
		t.Fatalf("expected 2 panes in active window, got %d", len(panes))
	}
	for _, p := range panes {
		if p.PanesInWindow != 2 {
			t.Fatalf("expected panesInWindow=2, got %d", p.PanesInWindow)
		}
	}
	if panes[1].PaneID != "%2" || panes[1].Cwd != "/home/b" || panes[1].Cmd != "vim" {
		t.Fatalf("unexpected active pane fields: %+v", panes[1])
	}
	if panes[1].Left != 80 || panes[1].Width != 80 {
		t.Fatalf("unexpected geometry: %+v", panes[1])
	}
}

func TestParsePanesLastPaneInWindow(t *testing.T) {
	panes, _ := parsePanes("%1\t1\t0\t0\t80\t24\t/home/a\tbash\t@0")
	if len(panes) != 1 || panes[0].PanesInWindow != 1 {
		t.Fatalf("expected a single pane with panesInWindow=1, got %+v", panes)
	}
}

func TestParsePanesEmptyAndMalformed(t *testing.T) {
	if panes, window := parsePanes(""); panes != nil || window != "" {
		t.Fatalf("expected nil/empty for blank input, got %+v %q", panes, window)
	}
	// 少一个字段的行应该被跳过，不 panic、不产生半条记录
	panes, _ := parsePanes("%1\t1\t0\t0\t80\t24\t/home/a\tbash")
	if len(panes) != 0 {
		t.Fatalf("expected malformed row to be skipped, got %+v", panes)
	}
}

// ── 真实 tmux 集成测试：结构化关闭只删目标 pane，不影响同窗口其它 pane ──
//
// pane.go 里的 tmux 调用走 tmuxBinary()（TMUX_BIN 可覆盖），这里同 worktree_e2e_test.go
// 的 e2eSetup 手法：用一个转发 `-L <隔离socket>` 的 wrapper 脚本当 TMUX_BIN，
// 测试只碰这个专属 socket，不影响开发机上任何真实会话。
//
// 会话名故意用 id.Valid() 认得的格式（YYYY-MMDD-HHMM-xxxx），让 a.sessionTarget 走
// resolveSession 里「已经是合法 id，直接返回」的分支，不需要真的起一个 ttmux CLI/TT client。
func paneE2ESetup(t *testing.T) (*gin.Engine, string) {
	t.Helper()
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("tmux not available")
	}
	tmp := t.TempDir()
	// 显式 socket 路径（-S）而不是共享命名空间的 -L <name>：每个测试的 t.TempDir() 天然
	// 互不相同，避免同名 socket 在测试间残留/复用导致「server exited unexpectedly」。
	sock := filepath.Join(tmp, "tmux.sock")
	wrapper := filepath.Join(tmp, "tmux-wrapper")
	if err := os.WriteFile(wrapper, []byte("#!/bin/sh\nexec tmux -S "+sock+" \"$@\"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("TMUX_BIN", wrapper)
	t.Cleanup(func() { _ = exec.Command("tmux", "-S", sock, "kill-server").Run() })

	name := "2026-0101-0000-tabc"
	if out, err := exec.Command(wrapper, "new-session", "-d", "-s", name, "-x", "80", "-y", "24").CombinedOutput(); err != nil {
		t.Fatalf("new-session: %v\n%s", err, out)
	}

	gin.SetMode(gin.TestMode)
	h := &API{}
	r := gin.New()
	r.GET("/sessions/:name/panes/active", h.ActivePane)
	r.POST("/sessions/:name/panes/:paneId/close", h.ClosePane)
	return r, name
}

func doJSON(t *testing.T, r *gin.Engine, method, path string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(method, path, nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	var body map[string]any
	if w.Body.Len() > 0 {
		if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
			t.Fatalf("bad json response: %v\nbody=%s", err, w.Body.String())
		}
	}
	return w.Code, body
}

func TestActivePaneReturnsGeometryAndImpactCount(t *testing.T) {
	r, name := paneE2ESetup(t)
	wrapper := os.Getenv("TMUX_BIN")
	run := func(args ...string) {
		if out, err := exec.Command(wrapper, args...).CombinedOutput(); err != nil {
			t.Fatalf("tmux %v: %v\n%s", args, err, out)
		}
	}
	run("split-window", "-t", name, "-h")
	run("select-pane", "-t", name+".0")

	code, body := doJSON(t, r, http.MethodGet, "/sessions/"+name+"/panes/active")
	if code != http.StatusOK {
		t.Fatalf("expected 200, got %d body=%v", code, body)
	}
	data := body["data"].(map[string]any)
	if data["panesInWindow"].(float64) != 2 {
		t.Fatalf("expected panesInWindow=2 (split into two), got %v", data["panesInWindow"])
	}
	if data["paneId"].(string) == "" {
		t.Fatalf("expected a non-empty paneId, got %+v", data)
	}
}

func TestClosePaneRemovesOnlyTargetAndVerifies(t *testing.T) {
	r, name := paneE2ESetup(t)
	wrapper := os.Getenv("TMUX_BIN")
	run := func(args ...string) string {
		out, err := exec.Command(wrapper, args...).CombinedOutput()
		if err != nil {
			t.Fatalf("tmux %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	run("split-window", "-t", name, "-h")
	run("select-pane", "-t", name+".0")

	_, body := doJSON(t, r, http.MethodGet, "/sessions/"+name+"/panes/active")
	target := body["data"].(map[string]any)["paneId"].(string)

	code, closeBody := doJSON(t, r, http.MethodPost, "/sessions/"+name+"/panes/"+url.PathEscape(target)+"/close")
	if code != http.StatusOK {
		t.Fatalf("expected close to succeed, got %d body=%v", code, closeBody)
	}

	remaining := run("list-panes", "-t", name, "-F", "#{pane_id}")
	if strings.Contains(remaining, target) {
		t.Fatalf("target pane %s still listed after close: %s", target, remaining)
	}
	if remaining == "" {
		t.Fatalf("expected the other split pane to survive, session has no panes left")
	}
}

func TestClosePaneRejectsBadPaneID(t *testing.T) {
	r, name := paneE2ESetup(t)
	code, body := doJSON(t, r, http.MethodPost, "/sessions/"+name+"/panes/not-a-pane-id/close")
	if code != http.StatusBadRequest {
		t.Fatalf("expected 400 for malformed pane id, got %d body=%v", code, body)
	}
}

func TestClosePaneOfLastPaneEndsSessionAndStillReportsSuccess(t *testing.T) {
	r, name := paneE2ESetup(t)
	_, body := doJSON(t, r, http.MethodGet, "/sessions/"+name+"/panes/active")
	target := body["data"].(map[string]any)["paneId"].(string)

	code, closeBody := doJSON(t, r, http.MethodPost, "/sessions/"+name+"/panes/"+url.PathEscape(target)+"/close")
	if code != http.StatusOK {
		t.Fatalf("closing the last pane (killing the whole session) should still report success, got %d body=%v", code, closeBody)
	}
}

func TestNativeTerminalActionAndWindowsAPI(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("unix shell integration test")
	}
	gin.SetMode(gin.TestMode)
	host := sessionhost.NewHost(sessionhost.Config{HostID: "api-pane-test", LogsDir: t.TempDir()})
	defer host.Shutdown(context.Background())

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	ref, err := host.Create(ctx, sessionbackend.CreateSpec{
		SessionID: "native-api-demo",
		Exe:       "/bin/sh",
		Cols:      100,
		Rows:      30,
	})
	if err != nil {
		t.Fatalf("Create: %v", err)
	}

	h := &API{NativeBackend: host}
	r := gin.New()
	r.GET("/sessions/:name/panes/active", h.ActivePane)
	r.POST("/sessions/:name/panes/:paneId/close", h.ClosePane)
	r.GET("/sessions/:name/windows", h.SessionWindows)
	r.POST("/sessions/:name/terminal-action", h.SessionTerminalAction)

	postJSON := func(path string, payload map[string]any) (int, map[string]any) {
		raw, _ := json.Marshal(payload)
		req := httptest.NewRequest(http.MethodPost, path, bytes.NewReader(raw))
		req.Header.Set("Content-Type", "application/json")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		var out map[string]any
		_ = json.Unmarshal(w.Body.Bytes(), &out)
		return w.Code, out
	}

	// 1. Initial GET /windows & GET /panes/active.
	code, winBody := doJSON(t, r, http.MethodGet, "/sessions/"+ref.SessionID+"/windows")
	if code != http.StatusOK {
		t.Fatalf("GET /windows = %d body=%v", code, winBody)
	}
	data := winBody["data"].(map[string]any)
	if data["backend"] != "native" || int(data["panesInWindow"].(float64)) != 1 {
		t.Fatalf("unexpected initial windows reply: %+v", data)
	}

	// 2. split-right -> panesInWindow becomes 2, next-pane cycles focus, ActivePane returns new pane.
	code, splitBody := postJSON("/sessions/"+ref.SessionID+"/terminal-action", map[string]any{"action": "split-right"})
	if code != http.StatusOK {
		t.Fatalf("split-right = %d body=%v", code, splitBody)
	}
	splitData := splitBody["data"].(map[string]any)
	if int(splitData["panesInWindow"].(float64)) != 2 {
		t.Fatalf("expected 2 panes after split-right, got %+v", splitData)
	}
	secondPane := splitData["activePaneId"].(string)

	code, nextBody := postJSON("/sessions/"+ref.SessionID+"/terminal-action", map[string]any{"action": "next-pane"})
	if code != http.StatusOK {
		t.Fatalf("next-pane = %d body=%v", code, nextBody)
	}
	if nextBody["data"].(map[string]any)["activePaneId"].(string) == secondPane {
		t.Fatalf("next-pane did not move focus away from %s", secondPane)
	}

	// 3. ClosePane closes the split pane cleanly via REST API.
	code, closeBody := doJSON(t, r, http.MethodPost, "/sessions/"+ref.SessionID+"/panes/"+url.PathEscape(secondPane)+"/close")
	if code != http.StatusOK {
		t.Fatalf("ClosePane(%s) = %d body=%v", secondPane, code, closeBody)
	}

	// 4. new-window -> 2 windows; prev-window -> back to window 1; close-window -> back to 1 window.
	code, newWinBody := postJSON("/sessions/"+ref.SessionID+"/terminal-action", map[string]any{"action": "new-window"})
	if code != http.StatusOK {
		t.Fatalf("new-window = %d body=%v", code, newWinBody)
	}
	wins := newWinBody["data"].(map[string]any)["windows"].([]any)
	if len(wins) != 2 {
		t.Fatalf("expected 2 windows after new-window, got %d", len(wins))
	}
	win2ID := newWinBody["data"].(map[string]any)["activeWindowId"].(string)

	code, prevBody := postJSON("/sessions/"+ref.SessionID+"/terminal-action", map[string]any{"action": "prev-window"})
	if code != http.StatusOK || prevBody["data"].(map[string]any)["activeWindowId"].(string) == win2ID {
		t.Fatalf("prev-window failed: code=%d body=%v", code, prevBody)
	}

	code, selectBody := postJSON("/sessions/"+ref.SessionID+"/terminal-action", map[string]any{"action": "select-window", "windowId": win2ID})
	if code != http.StatusOK || selectBody["data"].(map[string]any)["activeWindowId"].(string) != win2ID {
		t.Fatalf("select-window failed: code=%d body=%v", code, selectBody)
	}

	code, closeWinBody := postJSON("/sessions/"+ref.SessionID+"/terminal-action", map[string]any{"action": "close-window", "windowId": win2ID})
	if code != http.StatusOK || len(closeWinBody["data"].(map[string]any)["windows"].([]any)) != 1 {
		t.Fatalf("close-window failed: code=%d body=%v", code, closeWinBody)
	}
}
