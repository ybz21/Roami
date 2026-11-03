package api

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestManagedSwarmCannotUseLegacyDone(t *testing.T) {
	gin.SetMode(gin.TestMode)
	r := gin.New()
	a := &API{}
	r.POST("/swarms/:n/done", a.SwarmDone)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/swarms/sw-0123456789abcdef0123456789abcdef/done", nil))
	if w.Code != http.StatusConflict {
		t.Fatalf("legacy done must not bypass verification: %d %s", w.Code, w.Body.String())
	}
}

func TestManagedProjectionPreservesVerificationAndSessionIdentity(t *testing.T) {
	value := managedProjection(map[string]any{
		"id": "sw-team", "name": "Team", "state": "review", "mainConversationId": "main",
		"work": []any{map[string]any{"member_name": "reviewer", "state": "verifying", "task_id": "task", "attempt": map[string]any{"sessionId": "worker"}}},
	})
	member := value["members"].([]any)[0].(map[string]any)
	if value["name"] != "sw-team" || value["label"] != "Team" || value["supervisor"] != "" || member["status"] == "done" || member["session"] != "worker" {
		t.Fatalf("invalid managed identity or verification projection: %#v", value)
	}
}
