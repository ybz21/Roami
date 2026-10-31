package agentproviders

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func isolatedProviderStore(t *testing.T) (*Store, string) {
	t.Helper()
	home := t.TempDir()
	for key, value := range map[string]string{"HOME": home, "CLAUDE_CONFIG_DIR": filepath.Join(home, ".claude"), "CODEX_HOME": filepath.Join(home, ".codex"),
		"XDG_CONFIG_HOME": filepath.Join(home, ".config"), "OPENCODE_CONFIG": "", "OPENCODE_CONFIG_CONTENT": "", "PI_CODING_AGENT_DIR": filepath.Join(home, ".pi", "agent")} {
		t.Setenv(key, value)
	}
	bin := filepath.Join(home, "bin")
	if err := os.MkdirAll(bin, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(bin, "opencode"), []byte("#!/bin/sh\nprintf 'opencode v2.0.27\\n'\n"), 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin)
	return NewStore(filepath.Join(home, "roami-data")), home
}

func modelInput(kind string) ProfileInput {
	key := "fixture-provider-credential"
	protocol := "openai-responses"
	if kind == "claude" {
		protocol = "anthropic-messages"
	}
	return ProfileInput{Name: "Work gateway", BaseURL: "https://gateway.example/v1", Model: "test-model", Protocol: protocol, AuthMode: "api_key", APIKey: &key}
}

func TestProviderPresetsApplyRestoreAndDoNotExposeCredentials(t *testing.T) {
	for _, kind := range []string{"claude", "codex", "opencode", "pi"} {
		t.Run(kind, func(t *testing.T) {
			store, home := isolatedProviderStore(t)
			ctx := context.Background()
			config, err := loadNative(ctx, kind)
			if err != nil {
				t.Fatal(err)
			}
			for _, doc := range config.Documents {
				content := []byte("{\n // Keep this comment\n \"plugins\":[\"existing\"],\n}\n")
				if doc.IsTOML {
					content = []byte("# Keep this comment\nmodel = 'original-model'\nmodel_provider = 'openai'\nnotify = ['existing-hook']\n[mcp_servers.existing]\ncommand = 'keep-server'\n")
				} else if doc.Name == "settings" && kind == "claude" {
					content = []byte("{\n // Keep this comment\n \"model\":\"original-model\",\n \"env\":{\"ANTHROPIC_AUTH_TOKEN\":\"original-credential\",\"KEEP\":\"yes\"},\n \"hooks\": {\"SessionStart\": []},\n}\n")
				}
				if err := writePrivate(doc.Path, content); err != nil {
					t.Fatal(err)
				}
			}
			if err := writePrivate(filepath.Join(home, ".codex", "auth.json"), []byte(`{"existingLogin":"preserve"}`)); err != nil {
				t.Fatal(err)
			}
			before, _ := loadNative(ctx, kind)
			p, err := store.Save(ctx, kind, "", modelInput(kind))
			if err != nil {
				t.Fatal(err)
			}
			config, _ = loadNative(ctx, kind)
			if before.revision() != config.revision() {
				t.Fatal("saving a preset changed the native configuration")
			}
			view, err := store.Apply(ctx, kind, p.ID, before.revision())
			if err != nil || view.Current.Model != "test-model" || !view.Profiles[0].Applied || view.ActiveID != p.ID || !view.CanRestore {
				t.Fatalf("apply: %+v, %v", view, err)
			}
			encoded, _ := json.Marshal(view)
			if bytes.Contains(encoded, []byte("fixture-provider-credential")) || bytes.Contains(encoded, []byte("original-credential")) || !view.Profiles[0].HasKey {
				t.Fatalf("credential exposed in summary: %s", encoded)
			}
			if err := store.Delete(ctx, kind, p.ID); err == nil || err.Error() != "MODEL_PROFILE_ACTIVE" {
				t.Fatalf("active preset deleted: %v", err)
			}
			input := modelInput(kind)
			input.Model, input.APIKey = "next-model", nil
			if _, err := store.Save(ctx, kind, p.ID, input); err != nil {
				t.Fatal(err)
			}
			view, _ = store.View(ctx, kind)
			if view.Profiles[0].Applied || !view.Profiles[0].HasKey || view.Current.Model != "test-model" {
				t.Fatalf("editing a preset claimed it was applied: %+v", view)
			}
			view, err = store.Apply(ctx, kind, p.ID, view.Revision)
			if err != nil || view.Current.Model != "next-model" || !view.Profiles[0].Applied {
				t.Fatalf("apply edited preset: %+v, %v", view, err)
			}
			reopened := NewStore(filepath.Join(home, "roami-data"))
			view, err = reopened.View(ctx, kind)
			if err != nil || view.ActiveID != p.ID || !view.Profiles[0].Applied {
				t.Fatalf("restart lost preset: %+v, %v", view, err)
			}
			view, err = reopened.Restore(ctx, kind, view.Revision)
			if err != nil || view.ActiveID != "" || view.Profiles[0].Applied {
				t.Fatalf("restore failed: %+v, %v", view, err)
			}
			after, _ := loadNative(ctx, kind)
			originalFields, _ := before.capture(defaultFields(kind))
			restoredFields, _ := after.capture(defaultFields(kind))
			if digest(originalFields) != digest(restoredFields) {
				t.Fatalf("original defaults not restored: %s != %s", jsonValue(originalFields), jsonValue(restoredFields))
			}
			for _, doc := range after.Documents {
				if !bytes.Contains(doc.Data, []byte("Keep this comment")) {
					t.Fatalf("lost native comments: %s", doc.Data)
				}
			}
			login, _ := os.ReadFile(filepath.Join(home, ".codex", "auth.json"))
			if string(login) != `{"existingLogin":"preserve"}` {
				t.Fatal("changed official login")
			}
			if err := reopened.Delete(ctx, kind, p.ID); err != nil {
				t.Fatal(err)
			}
			info, err := os.Stat(filepath.Join(store.root, "provider-presets.json"))
			if err != nil || info.Mode().Perm() != 0600 {
				t.Fatalf("preset file not private: %v", err)
			}
		})
	}
}

func TestExternalNativeChangesRequireFreshRevision(t *testing.T) {
	store, _ := isolatedProviderStore(t)
	ctx := context.Background()
	p, _ := store.Save(ctx, "claude", "", modelInput("claude"))
	view, _ := store.View(ctx, "claude")
	config, _ := loadNative(ctx, "claude")
	path := config.Documents[0].Path
	if err := writePrivate(path, []byte(`{"model":"external-model","theme":"light"}`)); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Apply(ctx, "claude", p.ID, view.Revision); err == nil || err.Error() != "AGENT_CONFIG_CHANGED" {
		t.Fatalf("stale apply overwrote configuration: %v", err)
	}
	view, _ = store.View(ctx, "claude")
	view, err := store.Apply(ctx, "claude", p.ID, view.Revision)
	if err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(path)
	data, _ = patchJSON(data, []string{"model"}, jsonValue("external-model-again"))
	if err := writePrivate(path, data); err != nil {
		t.Fatal(err)
	}
	view, _ = store.View(ctx, "claude")
	if !view.Changed || view.ActiveID != "" || view.Profiles[0].Applied {
		t.Fatalf("external change kept applied status: %+v", view)
	}
	_, err = store.Restore(ctx, "claude", view.Revision)
	if err != nil {
		t.Fatal(err)
	}
	data, _ = os.ReadFile(path)
	values, _ := jsonDocument(data)
	if textAt(values, "theme") != "light" || textAt(values, "model") != "external-model" {
		t.Fatalf("restore changed unrelated fields: %s", data)
	}
}

func TestPresetValidationAndKeyEnvironmentReferences(t *testing.T) {
	store, _ := isolatedProviderStore(t)
	ctx := context.Background()
	input := modelInput("claude")
	input.KeyEnv, input.APIKey = "ROAMI_FIXTURE_MODEL_KEY", nil
	p, err := store.Save(ctx, "claude", "", input)
	if err != nil || p.HasKey || p.KeyEnv != input.KeyEnv {
		t.Fatalf("save env key: %+v, %v", p, err)
	}
	view, _ := store.View(ctx, "claude")
	t.Setenv(input.KeyEnv, "")
	if _, err := store.Apply(ctx, "claude", p.ID, view.Revision); err == nil || err.Error() != "MODEL_KEY_ENV_MISSING" {
		t.Fatalf("missing env key accepted: %v", err)
	}
	t.Setenv(input.KeyEnv, "fixture-env-credential")
	view, err = store.Apply(ctx, "claude", p.ID, view.Revision)
	if err != nil || !view.Profiles[0].Applied {
		t.Fatalf("env key apply: %+v, %v", view, err)
	}
	if strings.Contains(string(jsonValue(view)), "fixture-env-credential") {
		t.Fatal("environment credential leaked")
	}
	for _, token := range []string{"!touch /tmp/should-not-run", "${SECRET}", "{file:/etc/passwd}", "value\nextra"} {
		input := modelInput("pi")
		input.APIKey = &token
		if _, err := store.Save(ctx, "pi", "", input); err == nil {
			t.Fatalf("interpreted key accepted: %s", token)
		}
	}
	input = modelInput("codex")
	input.Protocol = "anthropic-messages"
	if _, err := store.Save(ctx, "codex", "", input); err == nil {
		t.Fatal("Codex accepted incompatible protocol")
	}
}

func TestMultiFileWriteFailureRollsBackAndPreservesPreset(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("requires file permission enforcement")
	}
	store, home := isolatedProviderStore(t)
	ctx := context.Background()
	config, _ := loadNative(ctx, "pi")
	original := []byte(`{"defaultProvider":"original","defaultModel":"original-model"}`)
	if err := writePrivate(config.Documents[0].Path, original); err != nil {
		t.Fatal(err)
	}
	protected := filepath.Join(home, "readonly")
	target := filepath.Join(protected, "models.json")
	if err := writePrivate(target, []byte(`{}`)); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, config.Documents[1].Path); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(protected, 0500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(protected, 0700) })
	p, _ := store.Save(ctx, "pi", "", modelInput("pi"))
	view, _ := store.View(ctx, "pi")
	if _, err := store.Apply(ctx, "pi", p.ID, view.Revision); err == nil || err.Error() != "AGENT_CONFIG_WRITE_FAILED" {
		t.Fatalf("partial failure was not reported: %v", err)
	}
	data, _ := os.ReadFile(config.Documents[0].Path)
	if !bytes.Equal(data, original) {
		t.Fatalf("first file not rolled back: %s", data)
	}
	view, err := store.View(ctx, "pi")
	if err != nil || view.Current.Model != "original-model" || view.Profiles[0].Applied {
		t.Fatalf("partial write claimed success: %+v, %v", view, err)
	}
}

func TestFirstApplyThroughConfigDirectorySymlinkKeepsRestoreState(t *testing.T) {
	store, home := isolatedProviderStore(t)
	target := filepath.Join(home, "dotfiles", "claude")
	if err := os.MkdirAll(target, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, filepath.Join(home, ".claude")); err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	p, err := store.Save(ctx, "claude", "", modelInput("claude"))
	if err != nil {
		t.Fatal(err)
	}
	view, err := store.View(ctx, "claude")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = store.Apply(ctx, "claude", p.ID, view.Revision); err != nil {
		t.Fatal(err)
	}
	reopened, err := store.View(ctx, "claude")
	if err != nil || !reopened.CanRestore || reopened.ActiveID != p.ID || !reopened.Profiles[0].Applied {
		t.Fatalf("symlink changed configuration identity: %+v %v", reopened, err)
	}
	if _, err = store.Restore(ctx, "claude", reopened.Revision); err != nil {
		t.Fatal(err)
	}
	if info, err := os.Lstat(filepath.Join(home, ".claude")); err != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Fatal("configuration directory symlink was replaced")
	}
}

func TestClaudeDefaultsAndCredentialsFollowSelectedModelAndRestore(t *testing.T) {
	for _, legacy := range []bool{false, true} {
		t.Run(map[bool]string{false: "first-apply", true: "existing-backup"}[legacy], func(t *testing.T) {
			store, home := isolatedProviderStore(t)
			ctx := context.Background()
			path := filepath.Join(home, ".claude", "settings.json")
			original := []byte(`{"model":"old-main","apiKeyHelper":"old-key-helper","modelPicker":{"replaceBuiltInOptions":true,"options":[{"model":"old-picker"}]},"env":{"ANTHROPIC_DEFAULT_SONNET_MODEL":"old-sonnet","ANTHROPIC_DEFAULT_OPUS_MODEL":"old-opus","ANTHROPIC_DEFAULT_HAIKU_MODEL":"old-haiku","KEEP":"yes"},"hooks":{"SessionStart":[]},"permissions":{"allow":["Read"]}}`)
			if err := writePrivate(path, original); err != nil {
				t.Fatal(err)
			}
			before, _ := loadNative(ctx, "claude")
			beforeFields, _ := before.capture(defaultFields("claude"))
			if legacy {
				err := store.locked(func(state *catalog) error {
					current := stateFor(state, "claude")
					current.Paths = configPaths(before)
					for _, f := range beforeFields {
						if len(f.Path) == 1 && f.Path[0] == "model" || len(f.Path) == 2 && containsLegacyClaudeField(f.Path[1]) {
							current.Original = append(current.Original, f)
						}
					}
					return store.save(state)
				})
				if err != nil {
					t.Fatal(err)
				}
			}
			input := modelInput("claude")
			input.AuthMode = "bearer"
			profile, err := store.Save(ctx, "claude", "", input)
			if err != nil {
				t.Fatal(err)
			}
			view, err := store.Apply(ctx, "claude", profile.ID, before.revision())
			if err != nil {
				t.Fatal(err)
			}
			data, _ := os.ReadFile(path)
			values, _ := jsonDocument(data)
			for _, key := range []string{"ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"} {
				if textAt(values, "env", key) != input.Model {
					t.Fatalf("%s kept the old model", key)
				}
			}
			if valueAt(values, []string{"apiKeyHelper"}) != nil || valueAt(values, []string{"modelPicker"}) != nil || textAt(values, "env", "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY") != "1" {
				t.Fatal("stale helper or picker overrides gateway configuration")
			}
			if textAt(values, "env", "KEEP") != "yes" || valueAt(values, []string{"hooks"}) == nil || valueAt(values, []string{"permissions"}) == nil {
				t.Fatal("changed unrelated Claude settings")
			}
			if _, err = store.Restore(ctx, "claude", view.Revision); err != nil {
				t.Fatal(err)
			}
			restored, _ := loadNative(ctx, "claude")
			afterFields, _ := restored.capture(defaultFields("claude"))
			if digest(beforeFields) != digest(afterFields) {
				t.Fatal("did not restore model aliases, helper and picker")
			}
		})
	}
}
func containsLegacyClaudeField(key string) bool {
	switch key {
	case "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL":
		return true
	}
	return false
}

func TestFactoryModeClearsCustomConnectionAndKeepsOriginalBackup(t *testing.T) {
	for _, kind := range []string{"claude", "codex", "opencode", "pi"} {
		t.Run(kind, func(t *testing.T) {
			store, home := isolatedProviderStore(t)
			ctx := context.Background()
			config, err := loadNative(ctx, kind)
			if err != nil {
				t.Fatal(err)
			}
			for _, doc := range config.Documents {
				raw := []byte(`{"model":"previous-model","hooks":{"keep":true},"permissions":{"keep":true}}`)
				if doc.IsTOML {
					raw = []byte("model = 'previous-model'\nmodel_provider = 'custom-before-roami'\n[mcp_servers.keep]\ncommand = 'preserve'\n[model_providers.openai]\nbase_url = 'https://old-relay.example'\n")
				} else if kind == "claude" {
					raw = []byte(`{"model":"previous-model","env":{"ANTHROPIC_BASE_URL":"https://old-relay.example","ANTHROPIC_AUTH_TOKEN":"original-token","KEEP":"yes"},"apiKeyHelper":"original-helper","hooks":{"keep":true},"permissions":{"keep":true}}`)
				}
				if err := writePrivate(doc.Path, raw); err != nil {
					t.Fatal(err)
				}
			}
			loginPath := filepath.Join(home, ".codex", "auth.json")
			if err := writePrivate(loginPath, []byte(`{"account":"keep"}`)); err != nil {
				t.Fatal(err)
			}
			before, _ := loadNative(ctx, kind)
			original, _ := before.capture(defaultFields(kind))
			profile, err := store.Save(ctx, kind, "", modelInput(kind))
			if err != nil {
				t.Fatal(err)
			}
			custom, err := store.Apply(ctx, kind, profile.ID, before.revision())
			if err != nil {
				t.Fatal(err)
			}
			official, err := store.UseOfficial(ctx, kind, custom.Revision)
			if err != nil {
				t.Fatal(err)
			}
			if official.Mode != "official" || official.ActiveID != "" || official.Profiles[0].Applied || !official.CanRestore {
				t.Fatalf("factory mode state: %+v", official)
			}
			cfg, _ := loadNative(ctx, kind)
			if cfg.current(kind).Model != "" {
				t.Fatal("factory mode kept custom model")
			}
			if kind == "claude" {
				raw, _ := os.ReadFile(cfg.Documents[0].Path)
				values, _ := jsonDocument(raw)
				if textAt(values, "env", "ANTHROPIC_BASE_URL") != "" || textAt(values, "env", "ANTHROPIC_AUTH_TOKEN") != "" || textAt(values, "apiKeyHelper") != "" {
					t.Fatal("factory mode restored the old custom provider")
				}
				if textAt(values, "env", "ROAMI_MODEL_MANAGED") != "1" || textAt(values, "env", "KEEP") != "yes" || valueAt(values, []string{"hooks"}) == nil {
					t.Fatal("lost ownership or unrelated settings")
				}
			}
			if kind == "codex" {
				if cfg.current(kind).Provider != "openai" {
					t.Fatal("factory Codex did not select OpenAI")
				}
				for _, doc := range cfg.Documents {
					if doc.Name == "config" {
						v, _ := doc.values()
						if textAt(v, "model_providers", "openai", "base_url") != "" || valueAt(v, []string{"mcp_servers", "keep"}) == nil {
							t.Fatal("kept OpenAI relay override or removed MCP")
						}
					}
				}
			}
			reopened := NewStore(filepath.Join(home, "roami-data"))
			v, err := reopened.View(ctx, kind)
			if err != nil || v.Mode != "official" || v.Changed {
				t.Fatalf("lost factory mode after reopen: %+v %v", v, err)
			}
			if len(reopened.Observations(ctx)) != 0 {
				t.Fatal("factory mode reported a custom provider preset")
			}
			if _, err := store.UseOfficial(ctx, kind, custom.Revision); err == nil || err.Error() != "AGENT_CONFIG_CHANGED" {
				t.Fatal("accepted stale factory switch")
			}
			if _, err := store.Restore(ctx, kind, v.Revision); err != nil {
				t.Fatal(err)
			}
			restored, _ := loadNative(ctx, kind)
			fields, _ := restored.capture(defaultFields(kind))
			if digest(original) != digest(fields) {
				t.Fatal("factory switch replaced the original recovery backup")
			}
			login, _ := os.ReadFile(loginPath)
			if string(login) != `{"account":"keep"}` {
				t.Fatal("changed account sign-in")
			}
		})
	}
}

func TestExistingOpenCodeConnectionIsShownAsCustom(t *testing.T) {
	store, _ := isolatedProviderStore(t)
	ctx := context.Background()
	cfg, err := loadNative(ctx, "opencode")
	if err != nil {
		t.Fatal(err)
	}
	if err := writePrivate(cfg.Documents[0].Path, []byte(`{"model":"team/model-a","providers":{"team":{"settings":{"baseURL":"https://custom.example"}}}}`)); err != nil {
		t.Fatal(err)
	}
	v, err := store.View(ctx, "opencode")
	if err != nil || v.Mode != "custom" {
		t.Fatalf("existing custom provider shown as factory: %+v %v", v, err)
	}
}
