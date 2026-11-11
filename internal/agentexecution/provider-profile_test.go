package agentexecution

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestRestoreProviderHomePreservesDefaultAndExplicitModes(t *testing.T) {
	for _, executor := range []string{"claude", "codex"} {
		for _, mode := range []string{"default", "explicit", "legacy"} {
			t.Run(executor+"/"+mode, func(t *testing.T) {
				home := t.TempDir()
				t.Setenv("HOME", home)
				key := providerHomeKey(executor)
				t.Setenv(key, filepath.Join(home, "unrelated-profile"))
				folder := ".codex"
				if executor == "claude" {
					folder = ".claude"
				}
				root := filepath.Join(home, folder)
				if mode != "default" {
					root = filepath.Join(home, "chosen-profile")
				}
				if err := os.MkdirAll(root, 0700); err != nil {
					t.Fatal(err)
				}
				binding := SessionBinding{ProviderHome: root}
				if mode != "legacy" {
					explicit := mode == "explicit"
					binding.ProviderHomeExplicit = &explicit
				}
				if err := restoreProviderHome(executor, binding); err != nil {
					t.Fatal(err)
				}
				value, exists := os.LookupEnv(key)
				if mode == "default" {
					if exists {
						t.Fatalf("default profile became explicit: %s", value)
					}
				} else if !exists || value != root {
					t.Fatalf("chosen profile lost: %q", value)
				}
				if got := providerHome(executor); got != root {
					t.Fatalf("home=%s", got)
				}
			})
		}
	}
}

func TestRestoreProviderHomeRejectsDefaultModeWithDifferentDirectory(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(home, "old"))
	for _, name := range []string{".claude", "custom"} {
		if err := os.MkdirAll(filepath.Join(home, name), 0700); err != nil {
			t.Fatal(err)
		}
	}
	explicit := false
	err := restoreProviderHome("claude", SessionBinding{ProviderHome: filepath.Join(home, "custom"), ProviderHomeExplicit: &explicit})
	if err == nil || err.Error() != "SESSION_RECOVERY_PROFILE_CHANGED" {
		t.Fatalf("err=%v", err)
	}
}

func TestProviderHomeModePersistsFalseAndKeepsLegacyUnknown(t *testing.T) {
	explicit := false
	for _, mode := range []*bool{nil, &explicit} {
		data, err := json.Marshal(SessionBinding{ProviderHomeExplicit: mode})
		if err != nil {
			t.Fatal(err)
		}
		var binding SessionBinding
		if err := json.Unmarshal(data, &binding); err != nil {
			t.Fatal(err)
		}
		if mode == nil {
			if binding.ProviderHomeExplicit != nil {
				t.Fatal("invented legacy mode")
			}
		} else if binding.ProviderHomeExplicit == nil || *binding.ProviderHomeExplicit {
			t.Fatal("lost default mode")
		}
	}
}
