package okr

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestProjectCapabilitiesPersistAndExposeRealGuidance(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(project, bundleRoot)
	if len(w.ProjectFiles.Skills) != 3 || !strings.Contains(w.ProjectFiles.MainInstructions, "current revision") {
		t.Fatalf("missing usable project guidance: %+v", w.ProjectFiles)
	}
	for _, skill := range w.ProjectFiles.Skills {
		body, err := os.ReadFile(filepath.Join(root, skill.Path))
		if err != nil || string(body) != skill.Content || hashText(body) != skill.SHA256 || !strings.Contains(skill.Content, "description:") {
			t.Fatalf("skill not backed by the actual file: %+v %v", skill, err)
		}
	}
	if body, err := os.ReadFile(filepath.Join(root, "data/observations.jsonl")); err != nil || len(body) != 0 {
		t.Fatal("seed invented observations", err)
	}
	custom := "# User-owned coordinator\nReview artifacts before acceptance.\n"
	if err := os.WriteFile(filepath.Join(root, "agents/main.md"), []byte(custom), 0600); err != nil {
		t.Fatal(err)
	}
	w.Config.Revision = w.Revision
	w, err = s.Save("project", w.Config)
	if err != nil || w.ProjectFiles.MainInstructions != custom {
		t.Fatal("save overwrote project instructions", err)
	}
	var main projectMainDefinition
	body, _ := os.ReadFile(filepath.Join(root, "agents/main.json"))
	if err := json.Unmarshal(body, &main); err != nil || len(main.Skills) != 3 || main.InstructionsFile != "main.md" {
		t.Fatal("agent configuration does not reference its actual skills", err)
	}
}

func TestProjectSkillReferencesRemainBoundToProjectFiles(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(project, bundleRoot)
	name := filepath.Join(root, "agents/main.json")
	editJSON(t, name, func(v map[string]any) { v["skills"] = []string{"../outside/SKILL.md"} })
	w, err = s.Get("project")
	if err != nil || !w.ProjectFiles.PendingChanges || len(w.ProjectFiles.Skills) != 0 {
		t.Fatal("unsafe staged reference became executable context", err)
	}
	editJSON(t, name, func(v map[string]any) { delete(v, "skills"); delete(v, "instructionsFile") })
	w, err = s.Get("project")
	if err != nil || w.ProjectFiles.PendingChanges || len(w.ProjectFiles.Skills) != 0 {
		t.Fatal("legacy two-field agent configuration rejected", err)
	}
}
