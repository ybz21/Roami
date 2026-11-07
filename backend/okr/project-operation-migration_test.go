package okr

import (
	"encoding/json"
	"path/filepath"
	"testing"

	storage "github.com/ybz21/Roami/internal/storage"
)

func TestOperationMigrationKeepsLegacyEvidenceAndFileOwnership(t *testing.T) {
	root := t.TempDir()
	paths := storage.Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
	if _, err := paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	descriptor := storage.DatabaseDescriptor{ID: "project-okr", Kind: "project-okr", Owner: "project-okr", Path: filepath.Join(paths.Database, "project-okr.db")}
	old, err := storage.OpenManaged(paths, descriptor, []storage.Step{{Version: 1, Name: "project OKR evidence", SQL: `
CREATE TABLE workspaces(project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
CREATE TABLE review_evidence(review_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL);
`}, {Version: 2, Name: "project file ownership", SQL: `CREATE TABLE file_workspaces(project_id TEXT PRIMARY KEY);`}}, storage.Options{})
	if err != nil {
		t.Fatal(err)
	}
	original, _ := json.Marshal(Workspace{ProjectID: "legacy", Config: testConfig(), Observations: []Observation{}, Reviews: []Review{}})
	if _, err = old.Exec(`INSERT INTO workspaces VALUES('legacy',7,?)`, string(original)); err != nil {
		t.Fatal(err)
	}
	if _, err = old.Exec(`INSERT INTO review_evidence VALUES('prior-review','legacy',7,?)`, string(original)); err != nil {
		t.Fatal(err)
	}
	if _, err = old.Exec(`INSERT INTO file_workspaces VALUES('file-project')`); err != nil {
		t.Fatal(err)
	}
	if err = old.Close(); err != nil {
		t.Fatal(err)
	}
	current, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	defer current.db.Close()
	for _, query := range []string{`SELECT body FROM workspaces WHERE project_id='legacy'`, `SELECT body FROM review_evidence WHERE review_id='prior-review'`} {
		var body string
		if err = current.db.QueryRow(query).Scan(&body); err != nil || body != string(original) {
			t.Fatal(body, err)
		}
	}
	var version, owned, operations int
	if err = current.db.QueryRow(`SELECT max(version) FROM schema_meta`).Scan(&version); err != nil || version != 3 {
		t.Fatal(version, err)
	}
	if err = current.db.QueryRow(`SELECT count(*) FROM file_workspaces WHERE project_id='file-project'`).Scan(&owned); err != nil || owned != 1 {
		t.Fatal(owned, err)
	}
	if err = current.db.QueryRow(`SELECT count(*) FROM project_operations`).Scan(&operations); err != nil || operations != 0 {
		t.Fatal(operations, err)
	}
}
