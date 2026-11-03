package okr

import (
	"os"
	"path/filepath"
	"testing"
)

func TestConfigReadOnlyDoesNotMigrateOrFallBackAfterConfirmation(t *testing.T) {
	s, _ := testStore(t)
	legacy, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	project := t.TempDir()
	s.SetProjects(func() map[string]string { return map[string]string{"project": project} })
	config, err := s.ConfigReadOnly("project")
	if err != nil || config == nil || config.Revision != legacy.Revision {
		t.Fatal(config, err)
	}
	if _, err := os.Stat(filepath.Join(project, ".roami")); !os.IsNotExist(err) {
		t.Fatal("read-only config migrated project", err)
	}
	var markers int
	if err := s.db.QueryRow(`SELECT count(*) FROM file_workspaces`).Scan(&markers); err != nil || markers != 0 {
		t.Fatal(markers, err)
	}
	confirmed, err := s.Get("project")
	if err != nil {
		t.Fatal(err)
	}
	c := confirmed.Config
	c.Objective = "Confirmed file objective"
	if _, err := s.Save("project", c); err != nil {
		t.Fatal(err)
	}
	config, err = s.ConfigReadOnly("project")
	if err != nil || config == nil || config.Objective != c.Objective {
		t.Fatal(config, err)
	}
	if err := os.Remove(filepath.Join(project, ".roami", "okr", "state", "current.json")); err != nil {
		t.Fatal(err)
	}
	if config, err := s.ConfigReadOnly("project"); err == nil || config != nil {
		t.Fatal("read-only binding fell back to stale archive", config, err)
	}
}
