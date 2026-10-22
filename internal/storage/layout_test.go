package metadb

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"sync"
	"testing"
)

func isolatedPaths(t *testing.T) Paths {
	t.Helper()
	root := t.TempDir()
	p := Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
	if _, e := p.Ensure(); e != nil {
		t.Fatal(e)
	}
	return p
}
func TestCatalogConcurrentRegistrationsPreserveAllEntries(t *testing.T) {
	p := isolatedPaths(t)
	const count = 16
	var wg sync.WaitGroup
	failures := make(chan error, count)
	for i := 0; i < count; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			failures <- p.Register(DatabaseDescriptor{ID: fmt.Sprint(i), Kind: "plugin", Owner: "test", Path: filepath.Join(p.Database, "plugins", fmt.Sprintf("%d.db", i))})
		}(i)
	}
	wg.Wait()
	close(failures)
	for e := range failures {
		if e != nil {
			t.Fatal(e)
		}
	}
	c, e := p.Catalog()
	if e != nil || len(c.Databases) != count {
		t.Fatalf("catalog entries=%d error=%v", len(c.Databases), e)
	}
}
func TestMaintenanceExcludesWritesAndNeverRemovesLock(t *testing.T) {
	p := isolatedPaths(t)
	release, e := p.Lock("storage", false)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = p.BackupSet(""); e == nil {
		t.Fatal("backup accepted an active writer")
	}
	release()
	lock := filepath.Join(p.Data, "locks", "storage.lock")
	before, e := os.Stat(lock)
	if e != nil {
		t.Fatal(e)
	}
	release, e = p.Lock("storage", true)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = p.Lock("storage", false); e == nil {
		t.Fatal("writer accepted during exclusive maintenance")
	}
	release()
	after, e := os.Stat(lock)
	if e != nil || !os.SameFile(before, after) {
		t.Fatal("persistent lock inode changed")
	}
}
func TestBackupRestoresIntoEmptyDirectoryWithMetadataAndWAL(t *testing.T) {
	p := isolatedPaths(t)
	d, e := OpenManaged(p, DatabaseDescriptor{ID: "main", Kind: "main", Path: p.MainPath(), Owner: "core"}, mainSteps, Options{HomeDir: p.Home, DataDir: p.Data})
	if e != nil {
		t.Fatal(e)
	}
	if _, e = d.Exec("INSERT INTO sessions(id,label) VALUES('backup-test','from WAL')"); e != nil {
		t.Fatal(e)
	}
	backup, e := p.BackupSet("")
	if e != nil {
		t.Fatal(e)
	}
	for _, name := range []string{"catalog.json", "storage-layout.json", "manifest.json", "meta.db"} {
		if _, e = os.Stat(filepath.Join(backup, name)); e != nil {
			t.Fatal(e)
		}
	}
	root := t.TempDir()
	target := Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
	if e = target.RestoreSet(backup); e != nil {
		t.Fatal(e)
	}
	original, _ := p.ReadLayout()
	restored, e := target.ReadLayout()
	if e != nil || restored.Instance != original.Instance || restored.Paths != target {
		t.Fatalf("restored layout=%+v err=%v", restored, e)
	}
	db, e := sql.Open("sqlite", "file:"+target.MainPath()+"?mode=ro")
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	var label string
	if e = db.QueryRow("SELECT label FROM sessions WHERE id='backup-test'").Scan(&label); e != nil || label != "from WAL" {
		t.Fatalf("restored label=%q err=%v", label, e)
	}
	if e = target.RestoreSet(backup); e == nil {
		t.Fatal("restore overwrote an existing instance")
	}
}
func TestLayoutMigrationRequiresOfflineAndPreservesSource(t *testing.T) {
	root := t.TempDir()
	p := Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
	legacy := filepath.Join(root, "meta.db")
	db, e := sql.Open("sqlite", legacy)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = db.Exec("CREATE TABLE marker(value TEXT); INSERT INTO marker VALUES('preserved')"); e != nil {
		t.Fatal(e)
	}
	db.Close()
	if _, e = p.Ensure(); e == nil {
		t.Fatal("silently opened a new instance over legacy data")
	}
	if e = p.MigrateLayout(false); e == nil {
		t.Fatal("legacy migration accepted without offline assertion")
	}
	if e = p.MigrateLayout(true); e != nil {
		t.Fatal(e)
	}
	if _, e = os.Stat(legacy); e != nil {
		t.Fatal("source database was removed")
	}
	db, e = sql.Open("sqlite", "file:"+p.MainPath()+"?mode=ro")
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	var value string
	if e = db.QueryRow("SELECT value FROM marker").Scan(&value); e != nil || value != "preserved" {
		t.Fatalf("marker=%s err=%v", value, e)
	}
}
func TestRestoreRejectsCorruptedSnapshot(t *testing.T) {
	p := isolatedPaths(t)
	_, e := OpenManaged(p, DatabaseDescriptor{ID: "main", Kind: "main", Path: p.MainPath(), Owner: "core"}, mainSteps, Options{HomeDir: p.Home, DataDir: p.Data})
	if e != nil {
		t.Fatal(e)
	}
	backup, e := p.BackupSet("")
	if e != nil {
		t.Fatal(e)
	}
	if e = os.WriteFile(filepath.Join(backup, "meta.db"), []byte("corrupt"), 0600); e != nil {
		t.Fatal(e)
	}
	if _, _, e = ValidateBackup(backup); e == nil {
		t.Fatal("accepted corrupted snapshot")
	}
}

func TestMissingRegisteredDatabaseDoesNotReinitialize(t *testing.T) {
	p := isolatedPaths(t)
	d, e := OpenManaged(p, DatabaseDescriptor{ID: "main", Kind: "main", Path: p.MainPath(), Owner: "core"}, mainSteps, Options{})
	if e != nil {
		t.Fatal(e)
	}
	if e = Discard(d.Path()); e != nil {
		t.Fatal(e)
	}
	if e = os.Remove(p.MainPath()); e != nil {
		t.Fatal(e)
	}
	if _, e = OpenManaged(p, DatabaseDescriptor{ID: "main", Kind: "main", Path: p.MainPath(), Owner: "core"}, mainSteps, Options{}); e == nil {
		t.Fatal("recreated a lost registered database")
	}
	if _, e = os.Stat(p.MainPath()); !os.IsNotExist(e) {
		t.Fatal("missing database was silently replaced")
	}
}

func TestInterruptedLayoutPublicationRecoversWithoutEmptyDatabase(t *testing.T) {
	root := t.TempDir()
	p := Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
	stage := filepath.Join(root, "stage")
	l := Layout{Version: LayoutVersion, Instance: "recover-me", Paths: p}
	if e := atomicJSON(filepath.Join(stage, "catalog.json"), Catalog{Version: LayoutVersion, Instance: l.Instance, DataRoot: p.Data}); e != nil {
		t.Fatal(e)
	}
	if e := atomicJSON(filepath.Join(root, "storage-migration.json"), layoutJournal{Layout: l, Stage: stage}); e != nil {
		t.Fatal(e)
	}
	if _, e := p.Ensure(); e == nil {
		t.Fatal("initialized over an interrupted publication")
	}
	if e := p.RecoverLayout(); e != nil {
		t.Fatal(e)
	}
	restored, e := p.ReadLayout()
	if e != nil || restored.Instance != l.Instance {
		t.Fatalf("layout=%+v error=%v", restored, e)
	}
}

func TestDatabaseRootRelocationPreservesInstanceIdentity(t *testing.T) {
	p := isolatedPaths(t)
	d, e := OpenManaged(p, DatabaseDescriptor{ID: "main", Kind: "main", Path: p.MainPath(), Owner: "core"}, mainSteps, Options{})
	if e != nil {
		t.Fatal(e)
	}
	before, e := p.ReadLayout()
	if e != nil {
		t.Fatal(e)
	}
	_ = Discard(d.Path())
	target := p
	target.Database = filepath.Join(p.Data, "moved-database")
	if e = target.MigrateLayout(true); e != nil {
		t.Fatal(e)
	}
	after, e := target.ReadLayout()
	if e != nil || before.Instance != after.Instance {
		t.Fatalf("identity changed: before=%s after=%s error=%v", before.Instance, after.Instance, e)
	}
	if _, e = p.ReadLayout(); e == nil {
		t.Fatal("old database root still allowed after relocation")
	}
}

func TestExplicitStoreRootCannotInheritAnotherDatabase(t *testing.T) {
	foreign := t.TempDir()
	t.Setenv("ROAMI_HOME", foreign)
	t.Setenv("ROAMI_DATA", foreign)
	t.Setenv("ROAMI_DATABASE_DIR", filepath.Join(foreign, "do-not-touch"))
	t.Setenv("ROAMI_BACKUP_DIR", filepath.Join(foreign, "backups"))
	root := t.TempDir()
	d, e := Open(root, Options{DataDir: root})
	if e != nil {
		t.Fatal(e)
	}
	if d.Path() != filepath.Join(root, "database", "meta.db") {
		t.Fatalf("escaped explicit root: %s", d.Path())
	}
	if _, e = os.Stat(filepath.Join(foreign, "do-not-touch")); !os.IsNotExist(e) {
		t.Fatal("explicit store touched another instance")
	}
}

func TestRestoreRejectsUnsupportedAgentSchema(t *testing.T) {
	p := isolatedPaths(t)
	_, err := OpenManaged(p, DatabaseDescriptor{ID: "agent-runtime", Kind: "agent", Owner: "python-agent", Path: filepath.Join(p.Database, "agents", "runtime.db")},
		[]Step{{Version: 1, Name: "first", SQL: "CREATE TABLE agent_test (id TEXT PRIMARY KEY)"}, {Version: 2, Name: "metadata", SQL: "ALTER TABLE agent_test ADD COLUMN metadata TEXT"}, {Version: 3, Name: "resources", SQL: "ALTER TABLE agent_test ADD COLUMN resources TEXT"}, {Version: 4, Name: "reminders", SQL: "ALTER TABLE agent_test ADD COLUMN reminders TEXT"}, {Version: 5, Name: "delivery", SQL: "ALTER TABLE agent_test ADD COLUMN delivery TEXT"}, {Version: 6, Name: "retention", SQL: "ALTER TABLE agent_test ADD COLUMN retention TEXT"}, {Version: 7, Name: "main", SQL: "ALTER TABLE agent_test ADD COLUMN main TEXT"}, {Version: 8, Name: "session_reports", SQL: "ALTER TABLE agent_test ADD COLUMN session_reports TEXT"}, {Version: 9, Name: "browser_tabs", SQL: "ALTER TABLE agent_test ADD COLUMN browser_tabs TEXT"}, {Version: 10, Name: "browser_groups", SQL: "ALTER TABLE agent_test ADD COLUMN browser_groups TEXT"}, {Version: 11, Name: "future", SQL: "ALTER TABLE agent_test ADD COLUMN future TEXT"}}, Options{HomeDir: p.Home, DataDir: p.Data})
	if err != nil {
		t.Fatal(err)
	}
	backup, err := p.BackupSet("")
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err = ValidateBackup(backup); err == nil {
		t.Fatal("newer Agent schema was accepted for restore")
	}
}

func TestRestoreAcceptsSupportedPythonAgentSchemaVersions(t *testing.T) {
	for _, version := range []int{1, 2, 3, 4, 5, 6, 7, 8, 9, 10} {
		t.Run(strconv.Itoa(version), func(t *testing.T) {
			p := isolatedPaths(t)
			steps := []Step{{Version: 1, Name: "first", SQL: "CREATE TABLE agent_test(id TEXT PRIMARY KEY)"}, {Version: 2, Name: "metadata", SQL: "ALTER TABLE agent_test ADD COLUMN metadata TEXT"}, {Version: 3, Name: "resources", SQL: "ALTER TABLE agent_test ADD COLUMN resources TEXT"}, {Version: 4, Name: "reminders", SQL: "ALTER TABLE agent_test ADD COLUMN reminders TEXT"}, {Version: 5, Name: "delivery", SQL: "ALTER TABLE agent_test ADD COLUMN delivery TEXT"}, {Version: 6, Name: "retention", SQL: "ALTER TABLE agent_test ADD COLUMN retention TEXT"}, {Version: 7, Name: "main", SQL: "ALTER TABLE agent_test ADD COLUMN main TEXT"}, {Version: 8, Name: "session_reports", SQL: "ALTER TABLE agent_test ADD COLUMN session_reports TEXT"}, {Version: 9, Name: "browser_tabs", SQL: "ALTER TABLE agent_test ADD COLUMN browser_tabs TEXT"}, {Version: 10, Name: "browser_groups", SQL: "ALTER TABLE agent_test ADD COLUMN browser_groups TEXT"}}
			_, err := OpenManaged(p, DatabaseDescriptor{ID: "agent-runtime", Kind: "agent", Owner: "python-agent", Path: filepath.Join(p.Database, "agents", "runtime.db")}, steps[:version], Options{HomeDir: p.Home, DataDir: p.Data})
			if err != nil {
				t.Fatal(err)
			}
			backup, err := p.BackupSet("")
			if err != nil {
				t.Fatal(err)
			}
			if _, _, err = ValidateBackup(backup); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestBackupCompatibilityTracksThePythonSchemaVersion(t *testing.T) {
	content, err := os.ReadFile(filepath.Join("..", "..", "agent-runtime", "src", "roami_agent", "storage", "migrations.py"))
	if err != nil {
		t.Fatal(err)
	}
	match := regexp.MustCompile(`(?m)^SCHEMA_VERSION = (\d+)$`).FindSubmatch(content)
	if len(match) != 2 {
		t.Fatal("Python schema version declaration missing")
	}
	version, err := strconv.Atoi(string(match[1]))
	if err != nil || version != maxPythonAgentSchemaVersion {
		t.Fatalf("Python schema %d and Go restore compatibility %d differ", version, maxPythonAgentSchemaVersion)
	}
}
