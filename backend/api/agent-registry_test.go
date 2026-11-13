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
	found := false
	for _, row := range body.Agents {
		if row.Kind == "deepseek" {
			found = true
			if row.Command != "dsh --profile headless --permission-mode danger-full-access" || row.Interactive {
				t.Fatalf("incorrect DSH metadata: %+v", row)
			}
		}
	}
	if !found {
		t.Fatal("uninstalled DeepSeek omitted")
	}
}
