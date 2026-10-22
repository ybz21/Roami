package agentproviders

import (
	"context"
	"os"
	"path/filepath"
	"testing"
)

func TestInterruptedApplyRecovery(t *testing.T) {
	for _, scenario := range []string{"uncommitted", "committed", "external-change"} {
		t.Run(scenario, func(t *testing.T) {
			store, _ := isolatedProviderStore(t)
			ctx := context.Background()
			before, err := loadNative(ctx, "pi")
			if err != nil {
				t.Fatal(err)
			}
			p := Profile{ID: "12345678901234567890123456789012", Name: "Fixture", BaseURL: "https://example.test/v1", Model: "fixture-model", Protocol: "openai-responses", APIKey: "fixture-key"}
			fields, _ := profileFields("pi", p, 0)
			after, err := before.render(fields)
			if err != nil {
				t.Fatal(err)
			}
			journal := applyJournal{ID: p.ID, Before: before.Documents, After: after.Documents}
			if err := store.locked(func(state *catalog) error {
				if scenario == "committed" {
					state.LastOperation = journal.ID
				}
				return store.save(state)
			}); err != nil {
				t.Fatal(err)
			}
			for _, doc := range after.Documents {
				if err := writePrivate(doc.Path, doc.Data); err != nil {
					t.Fatal(err)
				}
			}
			if err := writePrivate(filepath.Join(store.root, "pending-apply.json"), jsonValue(journal)); err != nil {
				t.Fatal(err)
			}
			if scenario == "external-change" {
				if err := writePrivate(after.Documents[1].Path, []byte(`{"external":true}`)); err != nil {
					t.Fatal(err)
				}
			}
			view, err := NewStore(filepath.Dir(filepath.Dir(store.root))).View(ctx, "pi")
			if scenario == "external-change" {
				if err == nil || err.Error() != "AGENT_CONFIG_RECOVERY_REQUIRED" {
					t.Fatalf("overwrote external edits: %v", err)
				}
				data, _ := os.ReadFile(after.Documents[1].Path)
				if string(data) != `{"external":true}` {
					t.Fatal("external configuration changed")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if scenario == "committed" {
				if view.Current.Model != "fixture-model" {
					t.Fatal("committed native configuration was rolled back")
				}
			} else {
				for _, doc := range before.Documents {
					if _, err := os.Stat(doc.Path); !os.IsNotExist(err) {
						t.Fatal("new partial file not removed")
					}
				}
			}
			if _, err := os.Stat(filepath.Join(store.root, "pending-apply.json")); !os.IsNotExist(err) {
				t.Fatal("journal was not cleared")
			}
		})
	}
}

func TestOpenCodeProviderFormats(t *testing.T) {
	for _, major := range []int{1, 2} {
		p := Profile{ID: "12345678901234567890123456789012", Name: "Fixture", BaseURL: "https://example.test/v1", Model: "fixture-model", Protocol: "openai-responses", KeyEnv: "FIXTURE_KEY"}
		fields, err := profileFields("opencode", p, major)
		if err != nil {
			t.Fatal(err)
		}
		config := nativeConfig{Major: major, Documents: []document{{Name: "config", Data: []byte(`{"unrelated":true}`)}}}
		rendered, err := config.render(fields)
		if err != nil {
			t.Fatal(err)
		}
		values, _ := rendered.Documents[0].values()
		group, packageKey, settingsKey := "providers", "package", "settings"
		if major == 1 {
			group, packageKey, settingsKey = "provider", "npm", "options"
		}
		if textAt(values, group, providerID(p), packageKey) == "" || textAt(values, group, providerID(p), settingsKey, "apiKey") != "{env:FIXTURE_KEY}" {
			t.Fatalf("invalid OpenCode v%d config: %s", major, rendered.Documents[0].Data)
		}
	}
}
