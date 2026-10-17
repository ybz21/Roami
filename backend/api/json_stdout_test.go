package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/ttmux"
)

// 返回 JSON 的端点只认 stdout。
//
// 插件 SDK 的 Logf 写的是 stderr（`[roam.cron] 已添加定时任务 …`），而底层的
// ttmux.Run 把两股合在一起——于是「新增定时任务」明明保存成功了，界面上弹的却是
// 「Unexpected token 'r', "[roam.cron]"… is not valid JSON」，真正的那行日志反倒
// 把结果盖掉了。
func fakeTT(t *testing.T, script string) *gin.Engine {
	t.Helper()
	bin := filepath.Join(t.TempDir(), "fake-ttmux")
	if err := os.WriteFile(bin, []byte("#!/bin/sh\n"+script), 0o755); err != nil {
		t.Fatal(err)
	}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.POST("/plugins/:id/run", (&API{TT: ttmux.New(bin)}).PluginRun)
	return r
}

func postRun(r *gin.Engine) *httptest.ResponseRecorder {
	req := httptest.NewRequest(http.MethodPost, "/plugins/roam.cron/run",
		strings.NewReader(`{"command":"cron.add","args":{"name":"zz"}}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	return w
}

func TestJSONIgnoresStderrLogs(t *testing.T) {
	w := postRun(fakeTT(t, "echo '[roam.cron] 已添加定时任务 zz' >&2\nprintf '{\"name\":\"zz\",\"enabled\":true}\\n'\n"))
	if w.Code != http.StatusOK {
		t.Fatalf("code = %d, body = %s", w.Code, w.Body.String())
	}
	var got map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &got); err != nil {
		t.Fatalf("响应必须是干净的 JSON：%v，body = %q", err, w.Body.String())
	}
	if got["name"] != "zz" {
		t.Errorf("name = %v, want zz", got["name"])
	}
}

// 命令自称成功却没吐 JSON：报 BAD_JSON，并把 stderr 原样带出来——
// 前端拿半截 JSON 只会抛解析错，把真正的原因盖掉。
func TestJSONReportsNonJSONOutput(t *testing.T) {
	w := postRun(fakeTT(t, "echo 'cron: 配置文件损坏' >&2\necho 'not json'\n"))
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("code = %d, want 500; body = %s", w.Code, w.Body.String())
	}
	if !strings.Contains(w.Body.String(), "配置文件损坏") {
		t.Errorf("错误消息该带上 stderr 的原文，got %s", w.Body.String())
	}
}

// 命令失败时，诊断信息通常在 stderr
func TestJSONFailureUsesStderr(t *testing.T) {
	w := postRun(fakeTT(t, "echo 'plugin not found: roam.cron' >&2\nexit 1\n"))
	if w.Code != http.StatusInternalServerError {
		t.Fatalf("code = %d, want 500", w.Code)
	}
	if !strings.Contains(w.Body.String(), "plugin not found") {
		t.Errorf("got %s", w.Body.String())
	}
}
