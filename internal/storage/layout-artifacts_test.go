package metadb

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestArtifactDatabaseRootMigrationKeepsPathsAndCompleteBackup(t *testing.T) {
	source, database, entry := artifactBackupInstance(t)
	before, err := source.ReadLayout()
	if err != nil {
		t.Fatal(err)
	}
	if err := Discard(database.Path()); err != nil {
		t.Fatal(err)
	}
	target := source
	target.Database = filepath.Join(source.Data, "moved-database")
	plan, err := PlanLayout(target)
	if err != nil || plan.Legacy || plan.Source == nil || plan.Source.Database != source.Database {
		t.Fatalf("source plan: %+v %v", plan, err)
	}
	if err := target.MigrateLayout(true); err != nil {
		t.Fatal(err)
	}
	catalog, err := target.Catalog()
	if err != nil || len(catalog.Databases) != 1 || catalog.Databases[0].Path != "agents/runtime.db" {
		t.Fatalf("changed database identity: %+v %v", catalog, err)
	}
	after, err := target.ReadLayout()
	if err != nil || after.Instance != before.Instance {
		t.Fatalf("changed instance: %+v %v", after, err)
	}
	if _, err := os.Stat(database.Path()); err != nil {
		t.Fatal("original database removed")
	}
	if err := transferArtifact(target.Data, "", entry); err != nil {
		t.Fatal(err)
	}
	backups, err := filepath.Glob(filepath.Join(target.Backup, "pre-layout-*"))
	if err != nil || len(backups) != 1 {
		t.Fatalf("missing pre-layout backup: %v %v", backups, err)
	}
	manifest, _, err := ValidateBackup(backups[0])
	if err != nil || manifest.Version != 2 || len(manifest.Artifacts) != 1 || manifest.Databases[0].SchemaVersion != 1 {
		t.Fatalf("incomplete backup: %+v %v", manifest, err)
	}
	restored := emptyRestorePaths(t)
	if err := restored.RestoreSet(backups[0]); err != nil {
		t.Fatal(err)
	}
	if err := transferArtifact(restored.Data, "", entry); err != nil {
		t.Fatal(err)
	}
	restoredLayout, err := restored.ReadLayout()
	if err != nil || restoredLayout.Instance != before.Instance {
		t.Fatal("backup lost source identity")
	}
}

func TestArtifactLayoutMigrationRejectsInvalidEvidenceBeforePublishing(t *testing.T) {
	for _, failure := range []string{"missing", "corrupt", "symlink"} {
		t.Run(failure, func(t *testing.T) {
			source, database, entry := artifactBackupInstance(t)
			if err := Discard(database.Path()); err != nil {
				t.Fatal(err)
			}
			blob := filepath.Join(source.Data, filepath.FromSlash(entry.Path))
			if err := os.Remove(blob); err != nil {
				t.Fatal(err)
			}
			switch failure {
			case "corrupt":
				if err := os.WriteFile(blob, []byte("changed"), 0400); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				outside := filepath.Join(t.TempDir(), "outside")
				if err := os.WriteFile(outside, []byte("preserve"), 0600); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(outside, blob); err != nil {
					t.Fatal(err)
				}
			}
			target := source
			target.Database = filepath.Join(source.Data, "moved-database")
			if err := target.MigrateLayout(true); err == nil {
				t.Fatal("invalid artifact layout published")
			}
			if _, err := source.ReadLayout(); err != nil {
				t.Fatalf("source layout changed: %v", err)
			}
			if _, err := os.Lstat(target.Database); !os.IsNotExist(err) {
				t.Fatal("failed migration published a target database")
			}
			if _, err := os.Lstat(filepath.Join(source.Data, "storage-migration.json")); !os.IsNotExist(err) {
				t.Fatal("failed preparation created a publication journal")
			}
		})
	}
}

func TestDataRootRelocationUsesCompleteBackupAndRestore(t *testing.T) {
	source, database, _ := artifactBackupInstance(t)
	if err := Discard(database.Path()); err != nil {
		t.Fatal(err)
	}
	target := emptyRestorePaths(t)
	data, err := os.ReadFile(filepath.Join(source.Data, "storage-layout.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(target.Data, "storage-layout.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	err = target.MigrateLayout(true)
	if err == nil || !strings.Contains(err.Error(), "backup and restore") {
		t.Fatalf("cross-root move without source maintenance lock: %v", err)
	}
	if _, err := source.ReadLayout(); err != nil {
		t.Fatal("cross-root attempt changed source")
	}
	if _, err := os.Lstat(target.Database); !os.IsNotExist(err) {
		t.Fatal("cross-root attempt published a partial instance")
	}
}

func TestLayoutRecoveryRechecksArtifactsBeforeUnblockingWriters(t *testing.T) {
	source, database, entry := artifactBackupInstance(t)
	layout, err := source.ReadLayout()
	if err != nil {
		t.Fatal(err)
	}
	catalog, err := source.Catalog()
	if err != nil {
		t.Fatal(err)
	}
	if err := Discard(database.Path()); err != nil {
		t.Fatal(err)
	}
	target := source
	target.Database = filepath.Join(source.Data, "moved-database")
	stage, err := os.MkdirTemp(filepath.Dir(target.Database), ".database-migrate-*")
	if err != nil {
		t.Fatal(err)
	}
	if err := snapshot(database.Path(), filepath.Join(stage, "agents/runtime.db")); err != nil {
		t.Fatal(err)
	}
	if err := atomicJSON(filepath.Join(stage, "catalog.json"), catalog); err != nil {
		t.Fatal(err)
	}
	layout.Paths = target
	journal := layoutJournal{Layout: layout, Stage: stage, ArtifactVerify: true, ArtifactRestore: true, Artifacts: []ArtifactBackupEntry{entry}}
	legacyView := journal
	legacyView.ArtifactVerify = false
	if err := finishArtifactRestore(target, legacyView); err == nil {
		t.Fatal("legacy recovery skipped the artifact verification fence")
	}
	if err := atomicJSON(filepath.Join(target.Data, "storage-migration.json"), journal); err != nil {
		t.Fatal(err)
	}
	blob := filepath.Join(source.Data, filepath.FromSlash(entry.Path))
	body, err := os.ReadFile(blob)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(blob); err != nil {
		t.Fatal(err)
	}
	if err := target.RecoverLayout(); err == nil {
		t.Fatal("missing evidence unblocked writers")
	}
	if _, err := target.ReadLayout(); err == nil {
		t.Fatal("incomplete publication appeared ready")
	}
	if err := os.WriteFile(blob, body, 0400); err != nil {
		t.Fatal(err)
	}
	if err := target.RecoverLayout(); err != nil {
		t.Fatal(err)
	}
	recovered, err := target.ReadLayout()
	if err != nil || recovered.Instance != layout.Instance {
		t.Fatalf("recovery identity: %+v %v", recovered, err)
	}
	if err := transferArtifact(target.Data, "", entry); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Lstat(filepath.Join(target.Data, "storage-migration.json")); !os.IsNotExist(err) {
		t.Fatal("successful recovery left writers blocked")
	}
}

func TestLayoutPreviewRejectsEscapingRegisteredDatabase(t *testing.T) {
	source, database, _ := artifactBackupInstance(t)
	if err := Discard(database.Path()); err != nil {
		t.Fatal(err)
	}
	catalog, err := source.Catalog()
	if err != nil {
		t.Fatal(err)
	}
	catalog.Databases[0].Path = "../outside.db"
	if err := atomicJSON(filepath.Join(source.Database, "catalog.json"), catalog); err != nil {
		t.Fatal(err)
	}
	if _, err := PlanLayout(source); err == nil {
		t.Fatal("catalog escaped its database root")
	}
}
