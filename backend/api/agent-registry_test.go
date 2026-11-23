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
		if row.Kind == "deepseek" || row.Kind == "gemini" {
			t.Fatal("removed Harness still advertised")
		}
		if row.Kind == "antigravity" && (row.Command != "agy" || row.DisplayName != "Antigravity CLI" || !row.Interactive || !row.CanInstall) {
			t.Fatalf("invalid Antigravity descriptor: %+v", row)
		}
	}
	for _, kind := range []string{"claude", "codex", "antigravity", "opencode", "pi"} {
		if !found[kind] {
			t.Fatalf("uninstalled agent %s omitted", kind)
		}
	}
}
