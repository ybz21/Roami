package agentexecution

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"testing"

	"github.com/ybz21/Roami/internal/agentproviders"
	"github.com/ybz21/Roami/internal/agentruntime"
	"github.com/ybz21/Roami/internal/modelgateway/directory"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func TestClaudeRecoveryUsesSavedFreeModelWithoutWritingProviderSettings(t *testing.T) {
	service := testService(t)
	storage, err := metadb.ResolvePaths(service.Runtime.HomeDir, service.Runtime.DataDir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := storage.Ensure(); err != nil {
		t.Fatal(err)
	}
	paths, err := agentruntime.Resolve(storage.Home, storage.Data)
	if err != nil {
		t.Fatal(err)
	}
	socket := httpapi.Socket(paths.Socket)
	if err := os.MkdirAll(filepath.Dir(socket), 0700); err != nil {
		t.Fatal(err)
	}
	listener, err := net.Listen("unix", socket)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	if err := os.Chmod(socket, 0600); err != nil {
		t.Fatal(err)
	}
	const gateway = "http://127.0.0.1:19147"
	const selected = "configured-vision"
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		if req.Method != http.MethodGet || req.Header.Get("X-Roami-Owner") != "local" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		switch req.URL.Path {
		case "/v1/model-gateway/models":
			rows := []directory.Row{
				{ID: selected, Configured: true, Enabled: true, Pricing: "confirmed-free"},
				{ID: "metered", Configured: true, Enabled: true, Pricing: "metered"},
				{ID: "quota-model", Configured: true, Enabled: true, Pricing: "unknown"},
				{ID: "unconfigured", Enabled: true, Pricing: "confirmed-free"},
				{ID: "hidden", Configured: true, Enabled: true, GatewayHidden: true, Pricing: "confirmed-free"},
				{ID: "disabled", Configured: true, Pricing: "free-only", FreeOnly: true},
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{"models": rows, "revision": "fixture"}})
		case "/v1/model-gateway/catalog":
			_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]string{"baseUrl": gateway, "revision": "fixture"}})
		default:
			http.NotFound(w, req)
		}
	})}
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(func() { server.Close() })
	ctx := context.Background()
	for _, model := range []string{"metered", "quota-model", "unknown", "unconfigured", "hidden", "disabled", "roami-claude/" + selected} {
		if _, err := service.claudeRecoveryGateway(ctx, model); err == nil || err.Error() != "SESSION_RECOVERY_MODEL_NOT_AVAILABLE" {
			t.Fatalf("%s: %v", model, err)
		}
	}
	for _, model := range []string{"metered", "quota-model", selected} {
		if config, err := service.claudeGateway(ctx, model, true); err != nil || config.BaseURL != gateway {
			t.Fatalf("explicit selection of %s: %+v %v", model, config, err)
		}
	}
	for _, model := range []string{"unknown", "unconfigured", "hidden", "disabled"} {
		if _, err := service.claudeGateway(ctx, model, true); err == nil || err.Error() != "SESSION_RECOVERY_MODEL_NOT_AVAILABLE" {
			t.Fatalf("unauthorized selection of %s: %v", model, err)
		}
	}
	profileHome := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", profileHome)
	t.Setenv("ANTHROPIC_BASE_URL", "")
	store := agentproviders.NewStore(paths.Storage.Data)
	view, err := store.View(ctx, "claude")
	if err != nil {
		t.Fatal(err)
	}
	fixtureKey := "node-test"
	profile, err := store.Save(ctx, "claude", "", agentproviders.ProfileInput{
		Name: "Roami Gateway", BaseURL: gateway, Model: "existing-model", Protocol: "anthropic-messages", AuthMode: "bearer", APIKey: &fixtureKey,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := store.Apply(ctx, "claude", profile.ID, view.Revision); err != nil {
		t.Fatal(err)
	}
	configPath := filepath.Join(profileHome, "settings.json")
	before, err := os.ReadFile(configPath)
	if err != nil {
		t.Fatal(err)
	}
	if got, err := service.claudeRecoveryModel(ctx, selected); err != nil || got != "roami-claude/"+selected {
		t.Fatalf("startup flag = %q, %v", got, err)
	}
	after, err := os.ReadFile(configPath)
	if err != nil || string(after) != string(before) {
		t.Fatal("existing profile settings changed")
	}
	t.Setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:19148")
	if _, err := service.claudeRecoveryModel(ctx, selected); err == nil || err.Error() != "SESSION_RECOVERY_GATEWAY_PROFILE_REQUIRED" {
		t.Fatalf("different gateway accepted: %v", err)
	}
}

func TestModelOverrideRequiresClaudeProviderRecovery(t *testing.T) {
	service := testService(t)
	base := Spec{Key: "fixture", Executor: "claude", SessionID: "session", Model: "configured-vision", Prompt: "continue"}
	for _, spec := range []Spec{
		base,
		{Key: base.Key, Executor: "codex", SessionID: base.SessionID, Model: base.Model, Prompt: base.Prompt, ResumeFrom: "prior", ResumeProvider: completionThread},
		{Key: base.Key, Executor: base.Executor, SessionID: base.SessionID, Model: base.Model, Prompt: base.Prompt, ResumeFrom: "prior"},
	} {
		if _, err := service.Launch(context.Background(), spec); err == nil || err.Error() != "INVALID_SESSION_EXECUTION_SPEC" {
			t.Fatalf("unscoped override accepted: %v", err)
		}
	}
}
