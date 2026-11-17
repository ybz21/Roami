package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/agent"
)

func TestAgentRegistryIncludesUninstalledHarnessesWithoutProbes(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	router := gin.New()
	router.GET("/agent/registry", (&API{}).AgentRegistry)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/agent/registry", nil))
	var body struct {
		Agents []agent.Descriptor `json:"agents"`
	}
	if response.Code != http.StatusOK || json.Unmarshal(response.Body.Bytes(), &body) != nil || len(body.Agents) != len(agent.Kinds()) {
		t.Fatalf("registry mismatch: %s", response.Body)
	}
	found := map[string]bool{}
	for _, row := range body.Agents {
		found[row.Kind] = true
		if row.Kind == "deepseek" {
			t.Fatal("removed Harness still advertised")
		}
	}
	for _, kind := range []string{"claude", "codex", "opencode", "pi"} {
		if !found[kind] {
			t.Fatalf("uninstalled agent %s omitted", kind)
		}
	}
}
