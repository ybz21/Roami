package metadb

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func artifactBackupInstance(t *testing.T) (Paths, *DB, ArtifactBackupEntry) {
	t.Helper()
	p := isolatedPaths(t)
	db, err := OpenManaged(p, DatabaseDescriptor{ID: "agent-runtime", Kind: "agent", Owner: "python-agent", Path: filepath.Join(p.Database, "agents", "runtime.db")},
		[]Step{{Version: 1, Name: "fixture", SQL: "CREATE TABLE artifacts(id TEXT,owner_id TEXT,path TEXT,sha256 TEXT,size_bytes INTEGER,deleted_ms INTEGER)"}}, Options{HomeDir: p.Home, DataDir: p.Data})
	if err != nil {
		t.Fatal(err)
	}
	body := []byte("private evidence\x00\xff")
	digest := sha256.Sum256(body)
	entry := ArtifactBackupEntry{SHA256: hex.EncodeToString(digest[:]), Size: int64(len(body))}
	entry.Path = artifactBlobPath(entry.SHA256)
	path := filepath.Join(p.Data, entry.Path)
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, body, 0400); err != nil {
		t.Fatal(err)
	}
	for _, owner := range []string{"alice", "bob"} {
		if _, err = db.Exec("INSERT INTO artifacts VALUES(?,?,?,?,?,NULL)", owner, owner, entry.Path, entry.SHA256, entry.Size); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = db.Exec("INSERT INTO artifacts VALUES('deleted','alice','deleted','invalid',1,1)"); err != nil {
		t.Fatal(err)
	}
	return p, db, entry
}

func emptyRestorePaths(t *testing.T) Paths {
	t.Helper()
	root := t.TempDir()
	return Paths{Home: root, Data: root, Database: filepath.Join(root, "database"), Backup: filepath.Join(root, "backups")}
}

func TestArtifactBackupRestoresSharedBytesAndOwnerReferences(t *testing.T) {
	p, _, entry := artifactBackupInstance(t)
	backup, err := p.BackupSet("")
	if err != nil {
		t.Fatal(err)
	}
	m, _, err := ValidateBackup(backup)
	if err != nil || m.Version != 2 || len(m.Artifacts) != 1 || m.Artifacts[0] != entry {
		t.Fatalf("manifest=%+v err=%v", m, err)
	}
	target := emptyRestorePaths(t)
	if err = target.RestoreSet(backup); err != nil {
		t.Fatal(err)
	}
	if err = transferArtifact(target.Data, "", entry); err != nil {
		t.Fatal(err)
	}
	db, err := sql.Open("sqlite", "file:"+filepath.Join(target.Database, "agents", "runtime.db")+"?mode=ro")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var owners, deleted int
	if err = db.QueryRow("SELECT count(DISTINCT owner_id) FROM artifacts WHERE deleted_ms IS NULL").Scan(&owners); err != nil || owners != 2 {
		t.Fatalf("owners=%d err=%v", owners, err)
	}
	if err = db.QueryRow("SELECT count(*) FROM artifacts WHERE deleted_ms IS NOT NULL").Scan(&deleted); err != nil || deleted != 1 {
		t.Fatal("tombstone missing", err)
	}
}

func TestArtifactBackupRefusesMissingCorruptAndSymlinkedFiles(t *testing.T) {
	for _, mode := range []string{"missing", "corrupt", "symlink", "forged-index"} {
		t.Run(mode, func(t *testing.T) {
			p, db, entry := artifactBackupInstance(t)
			path := filepath.Join(p.Data, entry.Path)
			switch mode {
			case "missing":
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
			case "corrupt":
				if err := os.Chmod(path, 0600); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte("tampered evidence!"), 0600); err != nil {
					t.Fatal(err)
				}
			case "symlink":
				if err := os.Remove(path); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink("/etc/passwd", path); err != nil {
					t.Fatal(err)
				}
			case "forged-index":
				if _, err := db.Exec("UPDATE artifacts SET path='../../outside' WHERE deleted_ms IS NULL"); err != nil {
					t.Fatal(err)
				}
			}
			destination := filepath.Join(p.Backup, "invalid")
			if _, err := p.BackupSet(destination); err == nil {
				t.Fatal("invalid artifact accepted")
			}
			if _, err := os.Stat(destination); !os.IsNotExist(err) {
				t.Fatal("failed backup was published")
			}
		})
	}
}

func TestArtifactRestoreRejectsIncompletePackageAndPreservesExistingDestination(t *testing.T) {
	p, _, entry := artifactBackupInstance(t)
	backup, err := p.BackupSet("")
	if err != nil {
		t.Fatal(err)
	}
	m, _, err := ValidateBackup(backup)
	if err != nil {
		t.Fatal(err)
	}
	m.Artifacts = nil
	if err = atomicJSON(filepath.Join(backup, "manifest.json"), m); err != nil {
		t.Fatal(err)
	}
	target := emptyRestorePaths(t)
	if err = target.RestoreSet(backup); err == nil {
		t.Fatal("incomplete manifest accepted")
	}
	if _, err = os.Stat(target.Database); !os.IsNotExist(err) {
		t.Fatal("restore published incomplete database")
	}
	m.Artifacts = []ArtifactBackupEntry{entry}
	if err = atomicJSON(filepath.Join(backup, "manifest.json"), m); err != nil {
		t.Fatal(err)
	}
	if err = os.MkdirAll(filepath.Join(target.Data, "agent-artifacts"), 0700); err != nil {
		t.Fatal(err)
	}
	if err = target.RestoreSet(backup); err == nil {
		t.Fatal("existing artifact directory overwritten")
	}
	if err = os.Remove(filepath.Join(backup, "files", entry.Path)); err != nil {
		t.Fatal(err)
	}
	if _, _, err = ValidateBackup(backup); err == nil {
		t.Fatal("missing backup blob accepted")
	}
}

func TestArtifactRestoreRecoversBeforeAndAfterFilePublication(t *testing.T) {
	for _, filePublished := range []bool{false, true} {
		t.Run(fmt.Sprint(filePublished), func(t *testing.T) {
			p, _, entry := artifactBackupInstance(t)
			backup, err := p.BackupSet("")
			if err != nil {
				t.Fatal(err)
			}
			m, c, err := ValidateBackup(backup)
			if err != nil {
				t.Fatal(err)
			}
			target := emptyRestorePaths(t)
			stage, err := os.MkdirTemp(target.Data, ".database-restore-*")
			if err != nil {
				t.Fatal(err)
			}
			for _, d := range c.Databases {
				if err = snapshot(filepath.Join(backup, d.Path), filepath.Join(stage, d.Path)); err != nil {
					t.Fatal(err)
				}
			}
			c.DataRoot = target.Data
			if err = atomicJSON(filepath.Join(stage, "catalog.json"), c); err != nil {
				t.Fatal(err)
			}
			fileStage, err := os.MkdirTemp(target.Data, ".agent-artifacts-restore-*")
			if err != nil {
				t.Fatal(err)
			}
			if err = transferArtifact(filepath.Join(backup, "files"), fileStage, entry); err != nil {
				t.Fatal(err)
			}
			m.Layout.Paths = target
			journal := layoutJournal{Layout: m.Layout, Stage: stage, ArtifactRestore: true, Artifacts: m.Artifacts, ArtifactStage: fileStage}
			if err = atomicJSON(filepath.Join(target.Data, "storage-migration.json"), journal); err != nil {
				t.Fatal(err)
			}
			if err = os.Rename(stage, target.Database); err != nil {
				t.Fatal(err)
			}
			if filePublished {
				if err = os.Rename(filepath.Join(fileStage, "agent-artifacts"), filepath.Join(target.Data, "agent-artifacts")); err != nil {
					t.Fatal(err)
				}
			}
			if _, err = target.ReadLayout(); err == nil {
				t.Fatal("partial restore admitted writers")
			}
			if err = target.RestoreSet(backup); err == nil {
				t.Fatal("pending journal was overwritten")
			}
			if err = target.RecoverLayout(); err != nil {
				t.Fatal(err)
			}
			if err = transferArtifact(target.Data, "", entry); err != nil {
				t.Fatal(err)
			}
			if _, err = target.ReadLayout(); err != nil {
				t.Fatal(err)
			}
		})
	}
}
