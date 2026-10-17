package api

import (
	"bytes"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/ttmux"
)

// Keys 端点：白名单放行什么、tmux 收到的到底是哪几个参数。
//
// 用一个把 args 逐行记下来的假 ttmux 当 Bin——这里要验的是「拼出来的命令行」，
// 不是 tmux 本身的行为。会话名用合法 id 格式，让 sessionTarget 直接返回、不去 list-sessions。
func keysSetup(t *testing.T) (*gin.Engine, string, func() string) {
	t.Helper()
	tmp := t.TempDir()
	log := filepath.Join(tmp, "args.log")
	bin := filepath.Join(tmp, "fake-ttmux")
	script := "#!/bin/sh\nfor a in \"$@\"; do printf '%s\\n' \"$a\" >> " + log + "; done\n"
	if err := os.WriteFile(bin, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	h := &API{TT: ttmux.New(bin)}
	r := gin.New()
	r.POST("/sessions/:name/keys", h.Keys)
	r.POST("/sessions/:name/type", h.SessionType)
	return r, "2026-0101-0000-tabc", func() string {
		b, _ := os.ReadFile(log)
		return string(b)
	}
}

func TestSessionTypeTargetsExactSession(t *testing.T) {
	r, name, args := keysSetup(t)
	req := httptest.NewRequest(http.MethodPost, "/sessions/"+name+"/type", bytes.NewBufferString(`{"text":"codex resume --last"}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != http.StatusOK {
		t.Fatalf("type returned %d: %s", w.Code, w.Body.String())
	}
	want := "send-keys\n-t\n=" + name + ":\n-l\ncodex resume --last\n"
	if got := args(); got != want {
		t.Fatalf("tmux args mismatch:\ngot  %q\nwant %q", got, want)
	}
}

func postKeys(t *testing.T, r *gin.Engine, name, body string) int {
	t.Helper()
	req := httptest.NewRequest(http.MethodPost, "/sessions/"+name+"/keys", bytes.NewBufferString(body))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w.Code
}

func TestKeysAllowsCtrlC(t *testing.T) {
	r, name, args := keysSetup(t)
	if code := postKeys(t, r, name, `{"keys":["C-c"]}`); code != http.StatusOK {
		t.Fatalf("expected C-c to be allowed, got %d", code)
	}
	want := "send-keys\n-t\n=" + name + ":\nC-c\n"
	if got := args(); got != want {
		t.Fatalf("tmux args mismatch:\ngot  %q\nwant %q", got, want)
	}
}

func TestKeysRejectsOtherControlKeys(t *testing.T) {
	r, name, args := keysSetup(t)
	// C-c 是有意开的一个口子，不是「放开所有 C-x」：C-d 会把 shell 关掉，
	// C-z 会把 agent 丢到后台停住——两者都不是「中断」，也都没人从界面上要过。
	for _, k := range []string{"C-d", "C-z", "kill-session", "Escape;C-c"} {
		if code := postKeys(t, r, name, `{"keys":["`+k+`"]}`); code != http.StatusBadRequest {
			t.Fatalf("expected %q to be rejected, got %d", k, code)
		}
	}
	if got := args(); got != "" {
		t.Fatalf("rejected keys must not reach tmux, got %q", got)
	}
}

// 对话页「+」里的「权限模式」发的就是 BTab（tmux 对 Shift+Tab 的叫法）：
// Claude Code 与 Codex 都用它轮换权限/审批档。这一枚掉出白名单，那一行会静默失效
// ——按钮照点、请求 400、界面什么也不说，正是最难发现的那种坏法。
func TestKeysAllowsShiftTab(t *testing.T) {
	r, name, args := keysSetup(t)
	if code := postKeys(t, r, name, `{"keys":["BTab"]}`); code != http.StatusOK {
		t.Fatalf("expected BTab to be allowed, got %d", code)
	}
	want := "send-keys\n-t\n=" + name + ":\nBTab\n"
	if got := args(); got != want {
		t.Fatalf("tmux args mismatch:\ngot  %q\nwant %q", got, want)
	}
}
