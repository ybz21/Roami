package server

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/auth"
)

func TestAgentRoutesUseExistingAuthAndDoNotExposeLocalCallbacks(t *testing.T) {
	gin.SetMode(gin.TestMode)
	router := gin.New()
	gate := auth.New("test-only-login", "", "", 5, 30, nil)
	group := router.Group("/api", gate.Middleware())
	mountAgentRuntime(group, Config{DataDir: t.TempDir()})
	for _, path := range []string{"/api/agent/status", "/api/agent/conversations", "/api/agent/notifications"} {
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, httptest.NewRequest("GET", path, nil))
		if recorder.Code != http.StatusUnauthorized {
			t.Errorf("%s bypassed auth: %d", path, recorder.Code)
		}
	}
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest("POST", "/api/agent/internal/report", nil))
	if recorder.Code != http.StatusNotFound {
		t.Errorf("private route mounted publicly: %d", recorder.Code)
	}
}
