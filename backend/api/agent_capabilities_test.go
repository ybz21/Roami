package api

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestAgentCapabilitiesCreatesEditableGuide(t *testing.T) {
	isolateTestStorage(t, t.TempDir())
	path := filepath.Join(os.Getenv("ROAMI_HOME"), agentCapabilitiesFile)
	initial, err := readAgentCapabilities()
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(initial, "{{FILE_BASE}}/tmp/report.md") || !strings.Contains(initial, "{{FILE_RAW_BASE}}?path=") || !strings.Contains(initial, "chrome tabs") {
		t.Fatalf("default guide missing capabilities: %q", initial)
	}
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0o600 {
		t.Fatalf("guide permissions: %v %v", info, err)
	}
	if err := os.WriteFile(path, []byte("我的自定义能力"), 0o600); err != nil {
		t.Fatal(err)
	}
	got, err := readAgentCapabilities()
	if err != nil || got != "我的自定义能力" {
		t.Fatalf("custom guide overwritten: %q %v", got, err)
	}
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/agent/capabilities", (&API{}).AgentCapabilities)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/agent/capabilities", nil))
	if w.Code != http.StatusOK || !strings.Contains(w.Body.String(), "我的自定义能力") {
		t.Fatalf("GET guide: %d %s", w.Code, w.Body.String())
	}
}
