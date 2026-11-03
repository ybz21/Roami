package okr

import (
	"context"
	"encoding/json"
	"errors"
	"math"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
	"time"

	storage "github.com/ybz21/Roami/internal/storage"
)

func testStore(t *testing.T) (*Store, storage.Paths) {
	t.Helper()
	root := t.TempDir()
	paths := storage.Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
	s, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	s.now = func() time.Time { return time.Date(2026, 11, 2, 16, 30, 0, 0, time.UTC) }
	return s, paths
}

func testConfig() Config {
	return Config{Objective: "Grow adoption", StartDate: "2026-11-01", EndDate: "2026-11-30", Metrics: []Metric{{ID: "users", Name: "Users", Unit: "people", Source: "manual"}}, KeyResults: []KeyResult{{ID: "reach", Title: "Reach users", Horizon: "short", MetricID: "users", Target: 100, Mode: "atLeast", DueDate: "2026-11-30"}}}
}

func TestStoreRestartHistoryAndReviewEvidence(t *testing.T) {
	s, paths := testStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	if w.Revision != 1 || w.Metrics[0].SourceKey != "manual:users" || len(w.Observations) != 0 || w.Observations == nil || w.Reviews == nil {
		t.Fatalf("unexpected new workspace: %+v", w)
	}
	w, err = s.Observe("project", 1, "users", "2026-11-03", 9, "first")
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.Observe("project", 2, "users", "2026-11-03", 7, "correction")
	if err != nil {
		t.Fatal(err)
	}
	w, err = s.Review("project", 3, "Two observations", "Follow up")
	if err != nil {
		t.Fatal(err)
	}
	if w.Reviews[0].EvidenceRevision != 3 {
		t.Fatal(w.Reviews)
	}
	var evidence string
	if err := s.db.QueryRow(`SELECT body FROM review_evidence WHERE review_id=?`, w.Reviews[0].ID).Scan(&evidence); err != nil {
		t.Fatal(err)
	}
	var snapshot Workspace
	if err := json.Unmarshal([]byte(evidence), &snapshot); err != nil || snapshot.Revision != 3 || len(snapshot.Observations) != 2 {
		t.Fatalf("evidence: %s %v", evidence, err)
	}
	config := w.Config
	config.Objective = "Updated objective"
	w, err = s.Save("project", config)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.db.DB.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	got, err := reopened.Get("project")
	if err != nil || !reflect.DeepEqual(got, w) {
		t.Fatalf("restart mismatch: %+v %v", got, err)
	}
	if len(got.Observations) != 2 || got.Observations[0].Value != 9 || got.Observations[1].Value != 7 || got.Observations[0].ID == got.Observations[1].ID {
		t.Fatal(got.Observations)
	}
	catalog, err := paths.Catalog()
	if err != nil || len(catalog.Databases) != 1 || catalog.Databases[0].ID != "project-okr" || catalog.Databases[0].State != "ready" {
		t.Fatalf("catalog: %+v %v", catalog, err)
	}
}

func TestRevisionRaceAndFailedWritePreserveData(t *testing.T) {
	s, paths := testStore(t)
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	other, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	other.now = s.now
	start := make(chan struct{})
	results := make(chan error, 2)
	var wait sync.WaitGroup
	for _, store := range []*Store{s, other} {
		wait.Add(1)
		go func(store *Store) {
			defer wait.Done()
			<-start
			_, err := store.Observe("project", w.Revision, "users", "2026-11-03", 1, "")
			results <- err
		}(store)
	}
	close(start)
	wait.Wait()
	close(results)
	succeeded, conflicts := 0, 0
	for err := range results {
		if err == nil {
			succeeded++
		} else if errors.Is(err, ErrConflict) {
			conflicts++
		} else {
			t.Fatal(err)
		}
	}
	if succeeded != 1 || conflicts != 1 {
		t.Fatalf("success=%d conflict=%d", succeeded, conflicts)
	}
	before, _ := s.Get("project")
	if _, err := s.db.Exec(`CREATE TRIGGER refuse_write BEFORE UPDATE ON workspaces BEGIN SELECT RAISE(FAIL,'simulated disk failure'); END`); err != nil {
		t.Fatal(err)
	}
	if _, err := s.Review("project", before.Revision, "Must roll back", ""); err == nil {
		t.Fatal("write unexpectedly succeeded")
	}
	after, _ := s.Get("project")
	if !reflect.DeepEqual(before, after) {
		t.Fatal("failed write changed evidence")
	}
	var snapshots int
	if err := s.db.QueryRow(`SELECT count(*) FROM review_evidence`).Scan(&snapshots); err != nil || snapshots != 0 {
		t.Fatalf("orphaned evidence: %d %v", snapshots, err)
	}
}

func TestValidationRejectsUnknownReferencesDatesAndNumbers(t *testing.T) {
	s, _ := testStore(t)
	changes := []func(*Config){
		func(c *Config) { c.KeyResults[0].MetricID = "missing" },
		func(c *Config) { c.StartDate = "2026-02-30" },
		func(c *Config) { c.EndDate = "2026-10-31" },
		func(c *Config) { c.KeyResults[0].DueDate = "2026-12-01" },
		func(c *Config) { c.KeyResults[0].Target = math.Inf(1) },
		func(c *Config) { c.KeyResults[0].Mode = "unknown" },
		func(c *Config) { c.Metrics = append(c.Metrics, c.Metrics[0]) },
		func(c *Config) { c.Metrics[0].Source = "unknown" },
		func(c *Config) {
			c.Metrics[0].Source = "github"
			c.Metrics[0].Repo = "https://evil.test/a/b"
			c.Metrics[0].Field = "stars"
		},
		func(c *Config) { c.Metrics[0].ID = "../path" },
	}
	for i, change := range changes {
		c := testConfig()
		change(&c)
		if _, err := s.Save("project", c); !errors.Is(err, ErrInvalid) {
			t.Fatalf("case %d: %v", i, err)
		}
	}
	if got, err := s.Get("project"); err != nil || got != nil {
		t.Fatalf("validation wrote workspace: %+v %v", got, err)
	}
	w, err := s.Save("project", testConfig())
	if err != nil {
		t.Fatal(err)
	}
	for _, date := range []string{"2026-10-31", "2026-11-04", "2026-11-31"} {
		if _, err := s.Observe("project", w.Revision, "users", date, 0, ""); !errors.Is(err, ErrInvalid) {
			t.Fatalf("accepted date %s: %v", date, err)
		}
	}
	if _, err := s.Observe("project", w.Revision, "users", "2026-11-03", math.NaN(), ""); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
	if _, err := s.Observe("project", w.Revision, "missing", "2026-11-03", 0, ""); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
	if _, err := s.Collect(context.Background(), GitHub{}, "missing", 0, false); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
}
