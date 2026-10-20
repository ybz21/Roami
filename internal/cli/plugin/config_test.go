package plugincmd

import (
	"bytes"
	"encoding/json"
	"path/filepath"
	"testing"
	"time"

	"github.com/ybz21/Roami/internal/plugin"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestConfigMasksDeclaredAndLegacySecretsWithoutChangingStoredValues(t *testing.T) {
	root := t.TempDir()
	t.Setenv("ROAMI_DATABASE_DIR", filepath.Join(root, "database"))
	t.Setenv("ROAMI_BACKUP_DIR", filepath.Join(root, "backups"))
	env := plugin.NewEnv(runtime.Runtime{HomeDir: filepath.Join(root, "home"), DataDir: filepath.Join(root, "data"), Now: time.Now})
	store, err := plugin.Open(env)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	m := plugin.Manifest{ManifestVersion: 1, ID: "acme.config-check", Publisher: "acme", Name: "config-check", Version: "1.0.0", Runtime: plugin.Runtime{Kind: "builtin"},
		Permissions: plugin.Perms{Secrets: []string{"legacy"}},
		Contributes: plugin.Contribs{ConfigFields: []plugin.ConfigField{{Key: "declared", Secret: true}, {Key: "short", Secret: true}, {Key: "empty", Secret: true}}}}
	if err := store.SyncBuiltin(m); err != nil {
		t.Fatal(err)
	}
	original := map[string]string{"declared": "abcdefghijklm", "short": "abc", "legacy": "legacy-value", "empty": "", "destination": "Roami"}
	if err := env.SaveConfig(m.ID, original); err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	if err := config(env, []string{m.ID}, &output); err != nil {
		t.Fatal(err)
	}
	var displayed map[string]string
	if err := json.Unmarshal(output.Bytes(), &displayed); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"declared", "short", "legacy"} {
		if displayed[key] != "********" {
			t.Fatalf("%s was not fully masked", key)
		}
	}
	if displayed["empty"] != "" || displayed["destination"] != "Roami" {
		t.Fatal("empty or ordinary configuration changed")
	}
	output.Reset()
	if err := config(env, []string{m.ID, "set", "destination", "Inbox"}, &output); err != nil {
		t.Fatal(err)
	}
	stored, err := env.LoadConfig(m.ID)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"declared", "short", "legacy"} {
		if stored[key] != original[key] {
			t.Fatalf("stored %s was overwritten by its display mask", key)
		}
	}
}
