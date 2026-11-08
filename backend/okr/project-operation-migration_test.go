package okr

import (
	"encoding/json"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	storage "github.com/ybz21/Roami/internal/storage"
)

func TestMemoryEditMigrationKeepsV3OperationBytesAndImmutability(t *testing.T) {
	root := t.TempDir()
	paths := storage.Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
	if _, err := paths.Ensure(); err != nil {
		t.Fatal(err)
	}
	descriptor := storage.DatabaseDescriptor{ID: "project-okr", Kind: "project-okr", Owner: "project-okr", Path: filepath.Join(paths.Database, "project-okr.db")}
	old, err := storage.OpenManaged(paths, descriptor, []storage.Step{{Version: 1, Name: "project OKR evidence", SQL: `
CREATE TABLE workspaces(project_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
CREATE TABLE review_evidence(review_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL);
`}, {Version: 2, Name: "project file ownership", SQL: `CREATE TABLE file_workspaces(project_id TEXT PRIMARY KEY);`}, {Version: 3, Name: "project operation receipts", SQL: `
CREATE TABLE project_operations(
 project_id TEXT NOT NULL,
 operation_key TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('review','observation','memory_append')),
 request_sha256 TEXT NOT NULL CHECK(length(request_sha256)=64),
 intent_json TEXT NOT NULL CHECK(json_valid(intent_json)),
 state TEXT NOT NULL CHECK(state IN ('prepared','applied')),
 receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json)),
 created_at TEXT NOT NULL,
 PRIMARY KEY(project_id,operation_key),
 CHECK((state='prepared' AND receipt_json IS NULL) OR (state='applied' AND receipt_json IS NOT NULL))
);
CREATE TRIGGER project_operation_identity BEFORE UPDATE OF project_id,operation_key,kind,request_sha256,intent_json,created_at ON project_operations BEGIN
 SELECT RAISE(ABORT,'PROJECT_OPERATION_IMMUTABLE');
END;
CREATE TRIGGER project_operation_applied BEFORE UPDATE ON project_operations WHEN OLD.state='applied' BEGIN
 SELECT RAISE(ABORT,'PROJECT_OPERATION_IMMUTABLE');
END;
`}}, storage.Options{})
	if err != nil {
		t.Fatal(err)
	}
	for _, row := range []struct {
		id      int
		key     string
		state   string
		receipt any
	}{{7, "prepared", "prepared", nil}, {19, "completed", "applied", `{"key": "completed", "note": "unchanged bytes"}`}} {
		if _, err := old.Exec(`INSERT INTO project_operations(rowid,project_id,operation_key,kind,request_sha256,intent_json,state,receipt_json,created_at) VALUES(?,'project',?,'memory_append',?, ?,?,?,?)`, row.id, row.key, strings.Repeat("a", 64), `{"content": "original  intent"}`, row.state, row.receipt, "2026-11-08T01:02:03Z"); err != nil {
			t.Fatal(err)
		}
	}
	readRows := func(db *storage.DB) []string {
		t.Helper()
		rows, err := db.Query(`SELECT json_array(rowid,project_id,operation_key,kind,request_sha256,intent_json,state,receipt_json,created_at) FROM project_operations ORDER BY rowid`)
		if err != nil {
			t.Fatal(err)
		}
		defer rows.Close()
		var values []string
		for rows.Next() {
			var value string
			if err := rows.Scan(&value); err != nil {
				t.Fatal(err)
			}
			values = append(values, value)
		}
		if err := rows.Err(); err != nil {
			t.Fatal(err)
		}
		return values
	}
	before := readRows(old)
	if err := old.Close(); err != nil {
		t.Fatal(err)
	}
	current, err := Open(paths)
	if err != nil {
		t.Fatal(err)
	}
	defer current.db.Close()
	if !reflect.DeepEqual(before, readRows(current.db)) {
		t.Fatal("migration changed existing operation bytes or row identity")
	}
	for _, query := range []string{
		`UPDATE project_operations SET operation_key='changed' WHERE operation_key='prepared'`,
		`UPDATE project_operations SET receipt_json='{}' WHERE operation_key='completed'`,
	} {
		if _, err := current.db.Exec(query); err == nil || !strings.Contains(err.Error(), "PROJECT_OPERATION_IMMUTABLE") {
			t.Fatal("migration lost the immutability guard", err)
		}
	}
}

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
	if err = current.db.QueryRow(`SELECT max(version) FROM schema_meta`).Scan(&version); err != nil || version != 4 {
		t.Fatal(version, err)
	}
	if err = current.db.QueryRow(`SELECT count(*) FROM file_workspaces WHERE project_id='file-project'`).Scan(&owned); err != nil || owned != 1 {
		t.Fatal(owned, err)
	}
	if err = current.db.QueryRow(`SELECT count(*) FROM project_operations`).Scan(&operations); err != nil || operations != 0 {
		t.Fatal(operations, err)
	}
}
