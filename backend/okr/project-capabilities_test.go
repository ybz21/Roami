package okr

import (
	"bytes"
	"encoding/json"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	okrtemplate "github.com/ybz21/Roami/skills"
)

func TestProjectCapabilitiesPersistAndExposeRealGuidance(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join(project, bundleRoot)
	mainText, err := okrtemplate.Files.ReadFile("okr-development/assets/.roami/okr/agents/main.md")
	if err != nil {
		t.Fatal(err)
	}
	if len(w.ProjectFiles.Skills) != 4 || w.ProjectFiles.MainInstructions != string(mainText) {
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
	if err := json.Unmarshal(body, &main); err != nil || len(main.Skills) != 4 || main.InstructionsFile != "main.md" {
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

func TestProjectWorkflowIsSeededOnlyForOKRAndPreservesProjectRules(t *testing.T) {
	s, project := fileStore(t)
	if w, err := s.Get("project"); err != nil || w != nil {
		t.Fatal(w, err)
	}
	if _, err := os.Stat(filepath.Join(project, "AGENTS.md")); !os.IsNotExist(err) {
		t.Fatal("ordinary project acquired OKR instructions", err)
	}
	custom := "# Existing project rules\nKeep the original inputs.\n"
	if err := os.WriteFile(filepath.Join(project, "AGENTS.md"), []byte(custom), 0600); err != nil {
		t.Fatal(err)
	}
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	if body, _ := os.ReadFile(filepath.Join(project, "AGENTS.md")); string(body) != custom {
		t.Fatal("existing project rules overwritten")
	}
	workflow, err := okrtemplate.Files.ReadFile("okr-development/assets/.roami/okr/AGENTS.md")
	if err != nil {
		t.Fatal(err)
	}
	if w.ProjectFiles.WorkflowFile != "AGENTS.md" || w.ProjectFiles.Workflow != string(workflow) {
		t.Fatal("daily/team guidance missing", w.ProjectFiles)
	}
	if strings.Contains(w.ProjectFiles.Workflow, "<task-id>/r<revision>/<run-id>") {
		t.Fatal("new project still prescribes execution identities as material directories")
	}
	os.Remove(filepath.Join(project, "AGENTS.md"))
	edited := "# Custom daily workflow\nUse dated evidence.\n"
	if err := os.WriteFile(filepath.Join(project, bundleRoot, "AGENTS.md"), []byte(edited), 0600); err != nil {
		t.Fatal(err)
	}
	w, err = s.Get("project")
	if err != nil || w.ProjectFiles.Workflow != edited {
		t.Fatal("workflow edit overwritten", err)
	}
	if body, _ := os.ReadFile(filepath.Join(project, "AGENTS.md")); !strings.Contains(string(body), ".roami/okr/AGENTS.md") {
		t.Fatal("missing project entry")
	}
}

func TestSavedProjectGetsExecutableCanonicalResourcesWithoutInventedState(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	if w.Config.Objective != testConfig().Objective || len(w.Observations) != 0 {
		t.Fatal("template changed the user's objective or invented facts")
	}
	root := filepath.Join(project, bundleRoot)
	for _, name := range []string{
		"manuals/data.md", "manuals/memory.md", "manuals/team.md", "manuals/publishing.md",
		"skills/dashboard-storage/scripts/sqlite_store.py", "skills/dashboard-storage/SKILL.md",
		"skills/collection-store/scripts/collection_store.py", "skills/daily-operations/scripts/wake_main.py",
		"skills/daily-operations/prompts/review.md", "data/.gitignore",
	} {
		want, err := okrtemplate.Files.ReadFile("okr-development/assets/.roami/okr/" + name)
		if err != nil {
			t.Fatal(err)
		}
		got, err := os.ReadFile(filepath.Join(root, name))
		if err != nil || !bytes.Equal(got, want) {
			t.Fatalf("canonical resource missing or changed: %s: %v", name, err)
		}
	}
	var schedule struct {
		Enabled bool `json:"enabled"`
	}
	body, err := os.ReadFile(filepath.Join(root, "schedules/daily.json"))
	if err != nil || json.Unmarshal(body, &schedule) != nil || schedule.Enabled {
		t.Fatal("new template enabled a schedule", err)
	}
	for _, name := range []string{"data/source.sqlite3", "data/collection.sqlite3", "connectors/source/connector.json"} {
		if _, err := os.Stat(filepath.Join(root, name)); !os.IsNotExist(err) {
			t.Fatalf("template created runtime or placeholder data: %s: %v", name, err)
		}
	}
	python, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("Python is required to exercise the installed source-store script")
	}
	script := filepath.Join(root, "skills/dashboard-storage/scripts/sqlite_store.py")
	command := exec.Command(python, script, "--project-root", project, "--project-id", "project", "init")
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("host-installed script could not initialize the project: %s: %v", output, err)
	}
	if body, err := os.ReadFile(filepath.Join(root, "data/observations.jsonl")); err != nil || len(body) != 0 {
		t.Fatal("source initialization fabricated confirmed observations", err)
	}
	custom := "# Project-specific data rules\n"
	name := filepath.Join(root, "manuals/data.md")
	if err := os.WriteFile(name, []byte(custom), 0600); err != nil {
		t.Fatal(err)
	}
	w.Config.Revision = w.Revision
	if _, err := s.Save("project", w.Config); err != nil {
		t.Fatal(err)
	}
	if body, _ := os.ReadFile(name); string(body) != custom {
		t.Fatal("template upgrade replaced existing project rules")
	}
	if info, err := os.Stat(filepath.Join(root, "data/source.sqlite3")); err != nil || info.Size() == 0 {
		t.Fatal("resaving the template removed the initialized source database", err)
	}
	if err := fs.WalkDir(okrtemplate.Files, ".", func(name string, item fs.DirEntry, err error) error {
		if strings.Contains(name, "__pycache__") || strings.HasSuffix(name, ".pyc") {
			t.Errorf("build embedded a generated Python cache: %s", name)
		}
		return err
	}); err != nil {
		t.Fatal(err)
	}
}

func TestCanonicalSeedRejectsSymlinkedProjectResourceDirectory(t *testing.T) {
	s, project := fileStore(t)
	if _, err := s.Save("project", testConfig()); err != nil {
		t.Fatal(err)
	}
	outside := t.TempDir()
	manuals := filepath.Join(project, bundleRoot, "manuals")
	if err := os.RemoveAll(manuals); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, manuals); err != nil {
		t.Fatal(err)
	}
	root, err := os.OpenRoot(filepath.Join(project, bundleRoot))
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	if err := seedProjectCapabilities(root); err == nil {
		t.Fatal("template followed a symlinked directory")
	}
	entries, err := os.ReadDir(outside)
	if err != nil || len(entries) != 0 {
		t.Fatal("template wrote outside the project", err)
	}
}
