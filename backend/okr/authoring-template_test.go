package okr

import (
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestCopiedGenericAuthoringTemplatePublishesConfirmedFacts(t *testing.T) {
	s, project := fileStore(t)
	if err := os.CopyFS(project, os.DirFS("../../skills/okr-development/assets")); err != nil {
		t.Fatal(err)
	}
	replace := strings.NewReplacer("\"{{target}}\"", "12", "{{objective}}", "Verify real outcomes", "{{startDate}}", "2026-11-01", "{{endDate}}", "2026-11-30", "{{metricName}}", "Verified outcomes", "{{unit}}", "items", "{{resultTitle}}", "Deliver verified results", "{{methodTitle}}", "Independent review", "{{channel}}", "review", "{{methodDescription}}", "Read actual artifacts", "{{acceptance}}", "Verify current files", "{{dashboardTitle}}", "Outcome dashboard")
	if err := filepath.WalkDir(project, func(name string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		data, err := os.ReadFile(name)
		if err != nil {
			return err
		}
		return os.WriteFile(name, []byte(replace.Replace(string(data))), 0600)
	}); err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(project, ".roami/okr")
	if _, err := os.Stat(filepath.Join(root, "state/current.json")); !os.IsNotExist(err) {
		t.Fatal("template fabricated a confirmed version", err)
	}
	var c Config
	if err := decodeJSONFile(filepath.Join(root, "okr.json"), &c); err != nil {
		t.Fatal(err)
	}
	if err := decodeJSONFile(filepath.Join(root, "dashboard.json"), &c.Dashboard); err != nil {
		t.Fatal(err)
	}
	if err := decodeJSONFile(filepath.Join(root, "agents/team.json"), &c.Team); err != nil {
		t.Fatal(err)
	}
	guidance := map[string]string{}
	for _, name := range []string{"AGENTS.md", ".roami/okr/AGENTS.md"} {
		data, err := os.ReadFile(filepath.Join(project, name))
		if err != nil || len(data) == 0 {
			t.Fatal("copied template lost agent instructions", name, err)
		}
		guidance[name] = string(data)
	}
	w, err := s.Save("project", c)
	if err != nil {
		t.Fatal(err)
	}
	for name, before := range guidance {
		data, err := os.ReadFile(filepath.Join(project, name))
		if err != nil || string(data) != before {
			t.Fatal("save replaced copied project instructions", name, err)
		}
	}
	if w.ProjectFiles.PendingChanges || len(w.Observations) != 0 || len(w.Team.Roles) != 0 {
		t.Fatalf("copied template is not a clean Main-only workspace: %+v", w)
	}
	w, err = s.Observe("project", w.Revision, "metric", "2026-11-03", 7, "fixture evidence")
	if err != nil || len(w.Observations) != 1 || w.Observations[0].Value != 7 {
		t.Fatal(w, err)
	}
	pointer, err := os.ReadFile(filepath.Join(root, "state/current.json"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = s.Save("project", c); !errors.Is(err, ErrConflict) {
		t.Fatal("stale template overwrote current facts", err)
	}
	after, _ := os.ReadFile(filepath.Join(root, "state/current.json"))
	if string(pointer) != string(after) {
		t.Fatal("rejected template changed the confirmed version")
	}
}

func decodeJSONFile(name string, value any) error {
	data, err := os.ReadFile(name)
	if err != nil {
		return err
	}
	return json.Unmarshal(data, value)
}
