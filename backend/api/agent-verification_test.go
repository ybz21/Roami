package api

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/agentinventory"
	"github.com/ybz21/Roami/internal/agentproviders"
)

func TestAgentVerificationRequiresSuccessfulReplyAndInvalidatesChangedBinary(t *testing.T) {
	root := t.TempDir()
	t.Setenv("HOME", root)
	t.Setenv("CODEX_HOME", filepath.Join(root, "codex-home"))
	t.Setenv("PATH", root+":"+os.Getenv("PATH"))
	binary := filepath.Join(root, "codex")
	workspace := filepath.Join(root, "probe-cwd")
	script := "#!/bin/sh\nif [ \"$1\" = --version ]; then echo codex-test; exit 0; fi\ncat >/dev/null\npwd > '" + workspace + "'\necho ROAMI_READY\n"
	if err := os.WriteFile(binary, []byte(script), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(os.Getenv("CODEX_HOME"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(os.Getenv("CODEX_HOME"), "config.toml"), []byte("model='fixture-alias'\n"), 0600); err != nil {
		t.Fatal(err)
	}
	a := &API{AgentVerification: NewAgentVerificationStore(root), AgentProviders: agentproviders.NewStore(root)}
	r := gin.New()
	r.POST("/verify/:kind", a.VerifyProfessionalAgent)
	request := func(kind string) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		r.ServeHTTP(w, httptest.NewRequest("POST", "/verify/"+kind, nil))
		return w
	}
	response := request("codex")
	if response.Code != 200 || !strings.Contains(response.Body.String(), `"verified":true`) {
		t.Fatalf("probe: %d %s", response.Code, response.Body.String())
	}
	cwd, _ := os.ReadFile(workspace)
	if !strings.Contains(string(cwd), "roami-agent-verification-") {
		t.Fatal("probe used a project directory", string(cwd))
	}
	if _, err := os.Stat(strings.TrimSpace(string(cwd))); !os.IsNotExist(err) {
		t.Fatal("probe directory leaked")
	}
	info, _ := os.Stat(a.AgentVerification.path("codex"))
	if info.Mode().Perm() != 0600 {
		t.Fatal("evidence is not private")
	}
	rows := []agentinventory.ProfessionalAgent{{Kind: "codex", Installed: true, Binary: binary, Authentication: "required"}}
	a.annotateAgentVerification(t.Context(), rows)
	if !rows[0].Verified {
		t.Fatal("proof not recovered")
	}
	marker := filepath.Join(root, "agents", "model-catalog-revision")
	if err := os.WriteFile(marker, []byte(`{"fixture-alias":"changed-source-with-same-alias"}`), 0600); err != nil {
		t.Fatal(err)
	}
	rows[0].Verified = false
	a.annotateAgentVerification(t.Context(), rows)
	if rows[0].Verified {
		t.Fatal("changed gateway source kept old verification")
	}
	if err := os.Remove(marker); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(binary, []byte(strings.ReplaceAll(script, "echo ROAMI_READY", "echo 'Reply with exactly ROAMI_READY.'")), 0700); err != nil {
		t.Fatal(err)
	}
	rows[0].Verified = false
	a.annotateAgentVerification(t.Context(), rows)
	if rows[0].Verified {
		t.Fatal("changed binary kept old verification")
	}
	response = request("codex")
	if response.Code != 502 {
		t.Fatal("echoing the prompt counted as success", response.Body.String())
	}
	if _, err := os.Stat(a.AgentVerification.path("codex")); !os.IsNotExist(err) {
		t.Fatal("failed verification retained old proof")
	}
	if request("other").Code != 400 {
		t.Fatal("unknown executor accepted")
	}
}

func TestClaudeVerificationTracksCredentialsWithoutStartupCounters(t *testing.T) {
	root := t.TempDir()
	t.Setenv("HOME", root)
	t.Setenv("CLAUDE_CONFIG_DIR", root)
	binary := filepath.Join(root, "claude")
	if err := os.WriteFile(binary, []byte("fixture"), 0700); err != nil {
		t.Fatal(err)
	}
	a := &API{}
	row := agentinventory.ProfessionalAgent{Kind: "claude", Installed: true, Binary: binary}
	before, err := a.verificationSignature(t.Context(), row)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".claude.json"), []byte(`{"numStartups":1}`), 0600); err != nil {
		t.Fatal(err)
	}
	after, _ := a.verificationSignature(t.Context(), row)
	if before != after {
		t.Fatal("startup metadata invalidated the probe")
	}
	if err := os.WriteFile(filepath.Join(root, ".credentials.json"), []byte(`{"token":"changed"}`), 0600); err != nil {
		t.Fatal(err)
	}
	after, _ = a.verificationSignature(t.Context(), row)
	if before == after {
		t.Fatal("custom credential directory was ignored")
	}
}
