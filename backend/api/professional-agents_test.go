package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestProfessionalAgentsWithoutPluginDaemon(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("PATH", t.TempDir())
	t.Setenv("CLAUDE_CONFIG_DIR", t.TempDir())
	t.Setenv("CLAUDE_CODE_OAUTH_TOKEN", "")
	router := gin.New()
	a := &API{}
	router.GET("/agent/professional", a.ProfessionalAgents)
	router.POST("/agent/professional/:kind/install", a.InstallProfessionalAgent)
	router.POST("/agent/professional/:kind/check", a.CheckProfessionalAgent)
	r := httptest.NewRecorder()
	router.ServeHTTP(r, httptest.NewRequest(http.MethodGet, "/agent/professional", nil))
	var body struct {
		Agents []struct {
			Kind string `json:"kind"`
		} `json:"agents"`
	}
	if r.Code != http.StatusOK || json.Unmarshal(r.Body.Bytes(), &body) != nil || len(body.Agents) < 4 {
		t.Fatalf("discovery failed: %d %s", r.Code, r.Body)
	}
	r = httptest.NewRecorder()
	router.ServeHTTP(r, httptest.NewRequest(http.MethodPost, "/agent/professional/unsupported/check", nil))
	if r.Code != http.StatusBadRequest {
		t.Fatalf("invalid check: %d %s", r.Code, r.Body)
	}
	r = httptest.NewRecorder()
	router.ServeHTTP(r, httptest.NewRequest(http.MethodPost, "/agent/professional/unsupported/install", nil))
	if r.Code != http.StatusBadRequest {
		t.Fatalf("invalid install: %d %s", r.Code, r.Body)
	}
}
