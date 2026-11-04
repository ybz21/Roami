package okr

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
)

func fileStore(t *testing.T) (*Store, string) {
	t.Helper()
	s, _ := testStore(t)
	project := t.TempDir()
	s.SetProjects(func() map[string]string { return map[string]string{"project": project} })
	return s, project
}

func editJSON(t *testing.T, name string, edit func(map[string]any)) {
	t.Helper()
	b, err := os.ReadFile(name)
	if err != nil {
		t.Fatal(err)
	}
	var v map[string]any
	if err := json.Unmarshal(b, &v); err != nil {
		t.Fatal(err)
	}
	edit(v)
	b, err = json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(name, b, 0600); err != nil {
		t.Fatal(err)
	}
}

func TestProjectFilesLifecycleSyncAndMemory(t *testing.T) {
	s, project := fileStore(t)
	if w, err := s.Get("project"); err != nil || w != nil {
		t.Fatal(w, err)
	}
	root := filepath.Join(project, ".roami", "okr")
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("ordinary project acquired files", err)
	}
	c := testConfig()
	c.Initiatives = []Initiative{{ID: "post", Title: "Publish introduction", Channel: "x", KeyResultIDs: []string{"reach"}, Acceptance: "Publication URL"}}
	w, err := s.Save("project", c)
	if err != nil {
		t.Fatal(err)
	}
	if w.ProjectFiles == nil || w.ProjectFiles.PendingChanges || w.ProjectFiles.TeamMemorySha256 != hashText(nil) || w.Dashboard == nil {
		t.Fatalf("metadata: %+v", w)
	}
	w, err = s.Observe("project", w.Revision, "users", "2026-11-03", 5, "original")
	if err != nil {
		t.Fatal(err)
	}
	if w.ProjectFiles.PendingChanges {
		t.Fatal("observation created a definition edit")
	}
	editJSON(t, filepath.Join(root, "okr.json"), func(v map[string]any) { v["objective"] = "Edited objective" })
	pending, err := s.Get("project")
	if err != nil || pending.Objective == "Edited objective" || !pending.ProjectFiles.PendingChanges {
		t.Fatal(pending, err)
	}
	if _, err := s.Save("project", pending.Config); !errors.Is(err, ErrPending) {
		t.Fatal("GUI save overwrote staged definitions", err)
	}
	w, err = s.Observe("project", w.Revision, "users", "2026-11-03", 3, "correction")
	if err != nil {
		t.Fatal(err)
	}
	if !w.ProjectFiles.PendingChanges {
		t.Fatal("observation lost pending definition")
	}
	if _, err := s.Sync("project", w.Revision-1); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
	w, err = s.Sync("project", w.Revision)
	if err != nil || w.Objective != "Edited objective" || w.ProjectFiles.PendingChanges || len(w.Observations) != 2 {
		t.Fatal(w, err)
	}
	w, err = s.WriteMemory("project", "# Team\nVerified with receipts.\n", w.ProjectFiles.TeamMemorySha256)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.WriteMemory("project", "overwrite", hashText(nil)); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
	before := *w
	w, err = s.Review("project", w.Revision, "Evidence", "Next")
	if err != nil {
		t.Fatal(err)
	}
	evidence, err := s.Evidence("project", w.Reviews[0].ID)
	if err != nil {
		t.Fatal(err)
	}
	before.ProjectFiles = nil
	if !reflect.DeepEqual(before, *evidence) {
		t.Fatalf("review snapshot changed: %+v %+v", before, evidence)
	}
	editJSON(t, filepath.Join(root, "connectors", "users", "connector.json"), func(v map[string]any) { v["execution"] = "shell" })
	if _, err := s.Sync("project", w.Revision); !errors.Is(err, ErrInvalid) {
		t.Fatal("custom execution accepted", err)
	}
	current, err := s.Get("project")
	if err != nil || current.Revision != w.Revision {
		t.Fatal(current, err)
	}
}

func TestProjectFilesMigratePreservesArchiveAndNeverFallsBack(t *testing.T) {
	s, paths := testStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.Observe("project", w.Revision, "users", "2026-11-03", 8, "legacy")
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.Review("project", w.Revision, "Legacy review", "")
	if err != nil {
		t.Fatal(err)
	}
	project := t.TempDir()
	s.SetProjects(func() map[string]string { return map[string]string{"project": project} })
	migrated, err := s.Get("project")
	if err != nil || migrated.Revision != w.Revision || len(migrated.Observations) != 1 {
		t.Fatal(migrated, err)
	}
	evidence, err := s.Evidence("project", w.Reviews[0].ID)
	if err != nil || evidence.Revision != 2 {
		t.Fatal(evidence, err)
	}
	archived, err := read(s.db, "project")
	if err != nil || archived.Revision != 3 {
		t.Fatal("legacy archive lost", archived, err)
	}
	migrated, err = s.Observe("project", migrated.Revision, "users", "2026-11-03", 7, "new")
	if err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	reopened.SetProjects(s.projects)
	got, err := reopened.Get("project")
	if err != nil || len(got.Observations) != 2 {
		t.Fatal(got, err)
	}
	pointer := filepath.Join(project, ".roami", "okr", "state", "current.json")
	if err := os.Remove(pointer); err != nil {
		t.Fatal(err)
	}
	if got, err := reopened.Get("project"); err == nil || got != nil {
		t.Fatal("fell back to legacy after pointer deletion", got, err)
	}
	if _, err := reopened.Save("project", migrated.Config); err == nil {
		t.Fatal("recreated missing pointer")
	}
}

func TestProjectFilesConcurrentWritersAndSymlinkDefense(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	start := make(chan struct{})
	results := make(chan error, 2)
	var wait sync.WaitGroup
	for i := 0; i < 2; i++ {
		wait.Add(1)
		go func() {
			defer wait.Done()
			<-start
			_, err := s.Observe("project", w.Revision, "users", "2026-11-03", 1, "")
			results <- err
		}()
	}
	close(start)
	wait.Wait()
	close(results)
	success, conflict := 0, 0
	for err := range results {
		if err == nil {
			success++
		} else if errors.Is(err, ErrConflict) {
			conflict++
		} else {
			t.Fatal(err)
		}
	}
	if success != 1 || conflict != 1 {
		t.Fatal(success, conflict)
	}
	memory := filepath.Join(project, ".roami", "okr", "memory", "team.md")
	outside := filepath.Join(t.TempDir(), "secret")
	if err := os.WriteFile(outside, []byte("private"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(memory); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, memory); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Get("project"); err == nil {
		t.Fatal("followed external symlink")
	}
	if _, err := s.WriteMemory("project", "changed", hashText([]byte("private"))); err == nil {
		t.Fatal("wrote external symlink")
	}
	b, _ := os.ReadFile(outside)
	if string(b) != "private" {
		t.Fatal("external file changed")
	}
}

func TestInitiativeAndDashboardReferences(t *testing.T) {
	s, _ := testStore(t)
	for _, edit := range []func(*Config){
		func(c *Config) {
			c.Initiatives = []Initiative{{ID: "post", Title: "Post", Channel: "x", KeyResultIDs: []string{"missing"}}}
		},
		func(c *Config) {
			c.Dashboard = &Dashboard{SchemaVersion: 1, Widgets: []DashboardWidget{{ID: "metric", Type: "script"}}}
		},
		func(c *Config) {
			c.Dashboard = &Dashboard{SchemaVersion: 1, Widgets: []DashboardWidget{{ID: "metric", Type: "metricTrend", MetricIDs: []string{"missing"}}}}
		},
	} {
		c := testConfig()
		edit(&c)
		if _, err := s.Save("project", c); !errors.Is(err, ErrInvalid) {
			t.Fatal(err)
		}
	}
}

func TestProjectFilesFailedPublishKeepsConfirmedRevision(t *testing.T) {
	s, project := fileStore(t)
	stale := testConfig()
	stale.Revision = 9
	if _, err := s.Save("project", stale); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
	root := filepath.Join(project, ".roami", "okr")
	if _, err := os.Stat(root); !os.IsNotExist(err) {
		t.Fatal("stale creation wrote files", err)
	}
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	_, err = s.mutateFiles("project", w.Revision, false, func(current *Workspace) error {
		current.Reviews = append(current.Reviews, Review{ID: "interrupted", Summary: "uncommitted", EvidenceRevision: current.Revision})
		records := filepath.Join(root, "data", "observations.jsonl")
		if err := os.Remove(records); err != nil {
			return err
		}
		return os.Mkdir(records, 0700)
	}, false)
	if err == nil {
		t.Fatal("publish over directory succeeded")
	}
	after, err := s.Get("project")
	if err != nil || after.Revision != w.Revision || len(after.Reviews) != 0 {
		t.Fatal("failed publication changed live evidence", after, err)
	}
	if _, err := s.Evidence("project", "interrupted"); !errors.Is(err, ErrNotFound) {
		t.Fatal("uncommitted evidence became visible", err)
	}
}

func TestProjectFilesBuiltinCodeIsReferenceAndNeverOverwritten(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	source := filepath.Join(project, ".roami", "okr", "connectors", "users", "store.go")
	code := []byte("user-authored connector source")
	if err := os.WriteFile(source, code, 0600); err != nil {
		t.Fatal(err)
	}
	pending, err := s.Get("project")
	if err != nil || !pending.ProjectFiles.PendingChanges {
		t.Fatal(pending, err)
	}
	if _, err := s.Sync("project", w.Revision); !errors.Is(err, ErrInvalid) {
		t.Fatal("edited reference was accepted as executed code", err)
	}
	if _, err := s.Save("project", w.Config); !errors.Is(err, ErrPending) {
		t.Fatal("GUI save accepted pending source", err)
	}
	after, _ := os.ReadFile(source)
	if string(after) != string(code) {
		t.Fatal("user code overwritten")
	}
}

func TestProjectFilesBuiltinReferenceUpgrade(t *testing.T) {
	s, project := fileStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	root, err := s.openBundle("project", false)
	if err != nil {
		t.Fatal(err)
	}
	defer root.Close()
	snapshot, err := loadSnapshot(root)
	if err != nil {
		t.Fatal(err)
	}
	reference := "connectors/users/store.go"
	previousVersion := []byte("previous builtin implementation reference\n")
	snapshot.ReferenceSources[reference] = hashText(previousVersion)
	if err := atomicFile(root, reference, previousVersion); err != nil {
		t.Fatal(err)
	}
	var pointer confirmedPointer
	if err := decodeFile(root, "state/current.json", &pointer); err != nil {
		t.Fatal(err)
	}
	if err := writeJSON(root, pointer.Snapshot, snapshot); err != nil {
		t.Fatal(err)
	}
	current, err := s.Get("project")
	if err != nil || current.ProjectFiles.PendingChanges {
		t.Fatal("untouched older reference marked as user edit", current, err)
	}
	current, err = s.Save("project", w.Config)
	if err != nil {
		t.Fatal(err)
	}
	if current.ProjectFiles.PendingChanges {
		t.Fatal("upgraded reference remains pending")
	}
	compiled, _ := builtinSources.ReadFile("store.go")
	exported, err := os.ReadFile(filepath.Join(project, ".roami", "okr", reference))
	if err != nil || !reflect.DeepEqual(compiled, exported) {
		t.Fatal("reference was not upgraded", err)
	}
}
