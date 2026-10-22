package metadb

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func nativeBackupInstance(t *testing.T) (Paths, NativeBackupEntry) {
	t.Helper()
	p, db, _ := artifactBackupInstance(t)
	if _, err := db.Exec("CREATE TABLE native_sessions(id TEXT PRIMARY KEY,flushed_seq INTEGER); CREATE TABLE native_session_segments(session_id TEXT,filename TEXT,sha256 TEXT)"); err != nil {
		t.Fatal(err)
	}
	id := "20261022T120000000Z-abcdef123456"
	directory := filepath.Join(p.Home, "agents", "native", id)
	if err := os.MkdirAll(directory, 0700); err != nil {
		t.Fatal(err)
	}
	for name, body := range map[string]string{".session.json": "{}\n", ".chat.jsonl": "{\"seq\":2}\n", "00000000000000000001-00000000000000000001.jsonl.gz": "immutable compressed journal"} {
		if err := os.WriteFile(filepath.Join(directory, name), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
	}
	entry, err := nativeEntry(p.Home, "agents/native/"+id+"/00000000000000000001-00000000000000000001.jsonl.gz")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = db.Exec("INSERT INTO native_sessions VALUES(?,2)", id); err != nil {
		t.Fatal(err)
	}
	if _, err = db.Exec("INSERT INTO native_session_segments VALUES(?,?,?)", id, filepath.Base(entry.Path), entry.SHA256); err != nil {
		t.Fatal(err)
	}
	return p, entry
}

func TestNativeBackupRestoresJournalAndSegments(t *testing.T) {
	source, segment := nativeBackupInstance(t)
	backup, err := source.BackupSet("")
	if err != nil {
		t.Fatal(err)
	}
	manifest, _, err := ValidateBackup(backup)
	if err != nil || manifest.Version != 3 || len(manifest.NativeFiles) != 3 {
		t.Fatalf("manifest=%+v error=%v", manifest, err)
	}
	target := emptyRestorePaths(t)
	if err = target.RestoreSet(backup); err != nil {
		t.Fatal(err)
	}
	for _, entry := range manifest.NativeFiles {
		if err = transferNativeFile(target.Home, "", entry); err != nil {
			t.Fatal(err)
		}
		info, err := os.Stat(filepath.Join(target.Home, entry.Path))
		if err != nil || info.Mode().Perm() != 0600 {
			t.Fatalf("file mode: %v %v", info, err)
		}
	}
	if err = os.WriteFile(filepath.Join(backup, "native-files", segment.Path), []byte("damaged"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, _, err = ValidateBackup(backup); err == nil {
		t.Fatal("corrupt native backup accepted")
	}
}

func TestNativeBackupRejectsMissingAndSymlinkSegments(t *testing.T) {
	for _, mode := range []string{"missing", "symlink", "corrupt"} {
		t.Run(mode, func(t *testing.T) {
			p, entry := nativeBackupInstance(t)
			path := filepath.Join(p.Home, entry.Path)
			switch mode {
			case "missing":
				os.Remove(path)
			case "symlink":
				os.Remove(path)
				os.Symlink(filepath.Join(p.Home, "config.yaml"), path)
			case "corrupt":
				os.WriteFile(path, []byte("changed"), 0600)
			}
			if _, err := p.BackupSet(""); err == nil {
				t.Fatal("unsafe native backup accepted")
			}
		})
	}
}

func TestNativeRestoreRecoveryVerifiesPublishedFiles(t *testing.T) {
	source, _ := nativeBackupInstance(t)
	backup, err := source.BackupSet("")
	if err != nil {
		t.Fatal(err)
	}
	manifest, _, err := ValidateBackup(backup)
	if err != nil {
		t.Fatal(err)
	}
	target := emptyRestorePaths(t)
	stage, err := os.MkdirTemp(target.Home, ".native-session-restore-*")
	if err != nil {
		t.Fatal(err)
	}
	journal := layoutJournal{NativeStage: stage, NativeFiles: manifest.NativeFiles}
	for _, entry := range manifest.NativeFiles {
		if err = transferNativeFile(filepath.Join(backup, "native-files"), stage, entry); err != nil {
			t.Fatal(err)
		}
	}
	if err = finishNativeRestore(target, journal); err != nil {
		t.Fatal(err)
	}
	if err = finishNativeRestore(target, journal); err != nil {
		t.Fatal(err)
	}
	entry := manifest.NativeFiles[0]
	if err = os.WriteFile(filepath.Join(target.Home, entry.Path), []byte("corrupt"), 0600); err != nil {
		t.Fatal(err)
	}
	if err = finishNativeRestore(target, journal); err == nil || !strings.Contains(err.Error(), "checksum") {
		t.Fatalf("corrupt recovery: %v", err)
	}
}
