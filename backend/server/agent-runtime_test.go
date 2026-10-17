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
	for _, path := range []string{"/api/agent/notification-deliveries", "/api/agent/reminders", "/api/agent/notification-preferences", "/api/agent/status", "/api/agent/conversations", "/api/agent/notifications", "/api/agent/artifacts", "/api/agent/artifacts/probe", "/api/agent/artifacts/probe/content", "/api/agent/tasks/probe/resources", "/api/agent/resources/probe", "/api/agent/tasks/probe/steering/operation"} {
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, httptest.NewRequest("GET", path, nil))
		if recorder.Code != http.StatusUnauthorized {
			t.Errorf("%s bypassed auth: %d", path, recorder.Code)
		}
	}
	for _, action := range []string{"pause", "resume"} {
		recorder := httptest.NewRecorder()
		router.ServeHTTP(recorder, httptest.NewRequest("POST", "/api/agent/resources/probe/"+action, nil))
		if recorder.Code != http.StatusUnauthorized {
			t.Errorf("control %s bypassed auth: %d", action, recorder.Code)
		}
	}
	recorder := httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest("POST", "/api/agent/tasks/probe/steer", nil))
	if recorder.Code != http.StatusUnauthorized {
		t.Errorf("steer bypassed auth: %d", recorder.Code)
	}
	recorder = httptest.NewRecorder()
	router.ServeHTTP(recorder, httptest.NewRequest("POST", "/api/agent/internal/report", nil))
	if recorder.Code != http.StatusNotFound {
		t.Errorf("private route mounted publicly: %d", recorder.Code)
	}
}
