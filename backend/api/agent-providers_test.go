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
	"github.com/ybz21/Roami/internal/agentproviders"
)

func TestAgentModelHTTPPrivateApplyAndConflicts(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(home, ".claude"))
	t.Setenv("PATH", t.TempDir())
	a := &API{AgentProviders: agentproviders.NewStore(filepath.Join(home, "data"))}
	r := gin.New()
	r.GET("/:kind/models", a.AgentModelProfiles)
	r.POST("/:kind/models", a.SaveAgentModelProfile)
	r.POST("/:kind/models/restore", a.RestoreAgentModelProfile)
	r.POST("/:kind/models/:profile/apply", a.ApplyAgentModelProfile)
	r.GET("/:kind/check", a.CheckProfessionalAgent)
	request := func(method, path, body string) *httptest.ResponseRecorder {
		t.Helper()
		out := httptest.NewRecorder()
		r.ServeHTTP(out, httptest.NewRequest(method, path, strings.NewReader(body)))
		return out
	}
	secret := "fixture-provider-" + "credential"
	saved := request("POST", "/claude/models", `{"name":"Gateway","baseUrl":"https://example.test","model":"fixture-model","protocol":"anthropic-messages","apiKey":"`+secret+`"}`)
	var body struct {
		Profile agentproviders.ProfileSummary `json:"profile"`
	}
	if saved.Code != http.StatusOK || json.Unmarshal(saved.Body.Bytes(), &body) != nil || body.Profile.ID == "" || strings.Contains(saved.Body.String(), secret) {
		t.Fatalf("save: %d %s", saved.Code, saved.Body)
	}
	if _, err := os.Stat(filepath.Join(home, ".claude", "settings.json")); !os.IsNotExist(err) {
		t.Fatal("save touched native config")
	}
	get := request("GET", "/claude/models", "")
	var view agentproviders.View
	if get.Code != 200 || json.Unmarshal(get.Body.Bytes(), &view) != nil {
		t.Fatalf("get: %s", get.Body)
	}
	apply := request("POST", "/claude/models/"+body.Profile.ID+"/apply", `{"revision":"`+view.Revision+`"}`)
	if apply.Code != 200 || strings.Contains(apply.Body.String(), secret) {
		t.Fatalf("apply: %d %s", apply.Code, apply.Body)
	}
	check := request("GET", "/claude/check", "")
	if check.Code != 200 || !strings.Contains(check.Body.String(), `"modelPreset":"Gateway"`) || !strings.Contains(check.Body.String(), "provider_managed") {
		t.Fatalf("check lost provider state: %s", check.Body)
	}
	stale := request("POST", "/claude/models/"+body.Profile.ID+"/apply", `{"revision":"`+view.Revision+`"}`)
	if stale.Code != 409 || !strings.Contains(stale.Body.String(), "AGENT_CONFIG_CHANGED") {
		t.Fatalf("stale: %d %s", stale.Code, stale.Body)
	}
	for _, input := range []string{`{"unknown":"` + secret + `"}`, `{} {}`, `{"name":"` + strings.Repeat("x", 65536) + `"}`} {
		result := request("POST", "/claude/models", input)
		if result.Code < 400 || strings.Contains(result.Body.String(), secret) {
			t.Fatalf("invalid input leaked or accepted: %d %s", result.Code, result.Body)
		}
	}
	if bad := request("GET", "/other/models", ""); bad.Code != 400 {
		t.Fatalf("unknown kind: %d", bad.Code)
	}
}

func TestAgentModelOptionsHTTP(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	secret := "fixture-model-" + "credential"
	denied := false
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/models" || r.Header.Get("Authorization") != "Bearer "+secret {
			t.Error("invalid upstream request")
		}
		if denied {
			w.WriteHeader(http.StatusUnauthorized)
			_, _ = w.Write([]byte(secret))
			return
		}
		_, _ = w.Write([]byte(`{"data":[{"id":"model-b"},{"id":"model-a"}]}`))
	}))
	defer upstream.Close()
	a := &API{AgentProviders: agentproviders.NewStore(t.TempDir())}
	r := gin.New()
	r.POST("/:kind/model-options", a.AgentModelOptions)
	request := func(kind, body string) *httptest.ResponseRecorder {
		t.Helper()
		out := httptest.NewRecorder()
		r.ServeHTTP(out, httptest.NewRequest("POST", "/"+kind+"/model-options", strings.NewReader(body)))
		return out
	}
	input, _ := json.Marshal(agentproviders.ModelQuery{ProfileInput: agentproviders.ProfileInput{BaseURL: upstream.URL + "/v1", Protocol: "openai-responses", APIKey: &secret}})
	result := request("codex", string(input))
	if result.Code != 200 || result.Body.String() != `{"models":["model-a","model-b"]}` {
		t.Fatalf("options: %d %s", result.Code, result.Body)
	}
	denied = true
	result = request("codex", string(input))
	if result.Code != 502 || !strings.Contains(result.Body.String(), "MODEL_LIST_UNAUTHORIZED") || strings.Contains(result.Body.String(), secret) {
		t.Fatalf("upstream error: %d %s", result.Code, result.Body)
	}
	for _, body := range []string{`{"unknown":"` + secret + `"}`, `{} {}`, `{"apiKey":"` + strings.Repeat("x", 65536) + `"}`} {
		result = request("codex", body)
		if result.Code < 400 || strings.Contains(result.Body.String(), secret) {
			t.Fatalf("invalid query: %d %s", result.Code, result.Body)
		}
	}
	if result = request("other", string(input)); result.Code != 400 {
		t.Fatalf("invalid kind: %d", result.Code)
	}
}
