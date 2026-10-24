package metadb

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"io"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

var nativeSessionID = regexp.MustCompile(`^[0-9]{8}T[0-9]{9}Z-[a-f0-9]{12}$`)
var nativeFilePath = regexp.MustCompile(`^agents/native/[0-9]{8}T[0-9]{9}Z-[a-f0-9]{12}/(\.session\.json|\.chat\.jsonl|[0-9]{20}-[0-9]{20}\.jsonl\.gz)$`)

type NativeBackupEntry struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"sizeBytes"`
}

func indexedNativeFiles(root string, databases []BackupEntry) (map[string]string, bool, error) {
	files := map[string]string{}
	present := false
	for _, descriptor := range databases {
		if descriptor.Kind != "agent" || descriptor.Owner != "python-agent" {
			continue
		}
		db, err := sql.Open("sqlite", "file:"+filepath.Join(root, descriptor.Path)+"?mode=ro")
		if err != nil {
			return nil, false, err
		}
		var exists int
		err = db.QueryRow("SELECT count(*) FROM sqlite_master WHERE name='native_sessions' AND type='table'").Scan(&exists)
		if err != nil {
			db.Close()
			return nil, false, err
		}
		if exists == 0 {
			db.Close()
			continue
		}
		present = true
		sessions, err := db.Query("SELECT id,flushed_seq FROM native_sessions")
		if err != nil {
			db.Close()
			return nil, false, err
		}
		for sessions.Next() {
			var id string
			var flushed int64
			if err = sessions.Scan(&id, &flushed); err != nil {
				break
			}
			if !nativeSessionID.MatchString(id) || flushed < 0 {
				err = fmt.Errorf("invalid native session identity")
				break
			}
			if flushed > 0 {
				files["agents/native/"+id+"/.session.json"] = ""
				files["agents/native/"+id+"/.chat.jsonl"] = ""
			}
		}
		if err == nil {
			err = sessions.Err()
		}
		sessions.Close()
		if err != nil {
			db.Close()
			return nil, false, err
		}
		segments, err := db.Query("SELECT session_id,filename,sha256 FROM native_session_segments")
		if err != nil {
			db.Close()
			return nil, false, err
		}
		for segments.Next() {
			var id, name, digest string
			if err = segments.Scan(&id, &name, &digest); err != nil {
				break
			}
			path := "agents/native/" + id + "/" + name
			if !nativeFilePath.MatchString(path) || !strings.HasSuffix(name, ".jsonl.gz") || !artifactDigest.MatchString(digest) {
				err = fmt.Errorf("invalid native segment index")
				break
			}
			files[path] = digest
		}
		if err == nil {
			err = segments.Err()
		}
		segments.Close()
		db.Close()
		if err != nil {
			return nil, false, err
		}
	}
	return files, present, nil
}

func openNativeFile(root, path string) (*os.File, error) {
	if !nativeFilePath.MatchString(path) {
		return nil, fmt.Errorf("invalid native file path")
	}
	current := root
	for _, part := range strings.Split(path, "/") {
		current = filepath.Join(current, part)
		info, err := os.Lstat(current)
		if err != nil {
			return nil, err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return nil, fmt.Errorf("native file symlink is unsupported")
		}
		if current != filepath.Join(root, filepath.FromSlash(path)) && !info.IsDir() {
			return nil, fmt.Errorf("invalid native directory")
		}
	}
	info, err := os.Lstat(current)
	if err != nil || !info.Mode().IsRegular() {
		return nil, fmt.Errorf("invalid native file")
	}
	f, err := os.Open(current)
	if err != nil {
		return nil, err
	}
	actual, err := f.Stat()
	if err != nil || !os.SameFile(info, actual) {
		f.Close()
		return nil, fmt.Errorf("native file changed")
	}
	return f, nil
}

func nativeEntry(root, path string) (NativeBackupEntry, error) {
	f, err := openNativeFile(root, path)
	if err != nil {
		return NativeBackupEntry{}, err
	}
	defer f.Close()
	hash := sha256.New()
	size, err := io.Copy(hash, f)
	return NativeBackupEntry{Path: path, SHA256: hex.EncodeToString(hash.Sum(nil)), Size: size}, err
}

func transferNativeFile(source, destination string, entry NativeBackupEntry) error {
	if !artifactDigest.MatchString(entry.SHA256) || entry.Size < 0 || entry.Size == math.MaxInt64 {
		return fmt.Errorf("invalid native manifest entry")
	}
	f, err := openNativeFile(source, entry.Path)
	if err != nil {
		return err
	}
	defer f.Close()
	var output *os.File
	hash := sha256.New()
	var writer io.Writer = hash
	if destination != "" {
		path := filepath.Join(destination, filepath.FromSlash(entry.Path))
		if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			return err
		}
		output, err = os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
		if err != nil {
			return err
		}
		defer output.Close()
		writer = io.MultiWriter(hash, output)
	}
	size, err := io.Copy(writer, io.LimitReader(f, entry.Size+1))
	if err != nil {
		return err
	}
	if size != entry.Size || hex.EncodeToString(hash.Sum(nil)) != entry.SHA256 {
		return fmt.Errorf("native file checksum failed")
	}
	if output != nil {
		if err = output.Sync(); err != nil {
			return err
		}
		return syncNativeDirectories(filepath.Dir(output.Name()), destination)
	}
	return nil
}

func backupNativeFiles(home, stage string, manifest *BackupManifest) error {
	indexed, present, err := indexedNativeFiles(stage, manifest.Databases)
	if err != nil {
		return err
	}
	if !present {
		return nil
	}
	manifest.Version = 3
	paths := make([]string, 0, len(indexed))
	for path := range indexed {
		paths = append(paths, path)
	}
	sort.Strings(paths)
	for _, path := range paths {
		entry, err := nativeEntry(home, path)
		if err != nil {
			return err
		}
		if indexed[path] != "" && entry.SHA256 != indexed[path] {
			return fmt.Errorf("native segment checksum failed")
		}
		if err = transferNativeFile(home, filepath.Join(stage, "native-files"), entry); err != nil {
			return err
		}
		manifest.NativeFiles = append(manifest.NativeFiles, entry)
	}
	return nil
}

func validateNativeBackup(root string, manifest BackupManifest) error {
	indexed, present, err := indexedNativeFiles(root, manifest.Databases)
	if err != nil {
		return err
	}
	if present && manifest.Version != 3 || len(indexed) != len(manifest.NativeFiles) {
		return fmt.Errorf("native backup package is incomplete")
	}
	seen := map[string]bool{}
	for _, entry := range manifest.NativeFiles {
		expected, ok := indexed[entry.Path]
		if !ok || seen[entry.Path] || expected != "" && expected != entry.SHA256 {
			return fmt.Errorf("native manifest does not match database")
		}
		seen[entry.Path] = true
		if err = transferNativeFile(filepath.Join(root, "native-files"), "", entry); err != nil {
			return err
		}
	}
	return nil
}

func finishNativeRestore(p Paths, journal layoutJournal) error {
	if journal.NativeStage == "" {
		return nil
	}
	if filepath.Dir(journal.NativeStage) != p.Home || !strings.HasPrefix(filepath.Base(journal.NativeStage), ".native-session-restore-") {
		return fmt.Errorf("invalid native restore staging path")
	}
	staged := filepath.Join(journal.NativeStage, "agents", "native")
	destination := filepath.Join(p.Home, "agents", "native")
	sourceInfo, sourceErr := os.Lstat(staged)
	targetInfo, targetErr := os.Lstat(destination)
	if sourceErr == nil {
		if !sourceInfo.IsDir() || !os.IsNotExist(targetErr) {
			return fmt.Errorf("native restore destination conflict")
		}
		if err := os.MkdirAll(filepath.Dir(destination), 0700); err != nil {
			return err
		}
		parent, err := os.Lstat(filepath.Dir(destination))
		if err != nil || !parent.IsDir() || parent.Mode()&os.ModeSymlink != 0 {
			return fmt.Errorf("invalid native restore directory")
		}
		if err = os.Rename(staged, destination); err != nil {
			return err
		}
	} else if !os.IsNotExist(sourceErr) || targetErr != nil || !targetInfo.IsDir() {
		return fmt.Errorf("native restore staging is missing")
	}
	for _, entry := range journal.NativeFiles {
		if err := transferNativeFile(p.Home, "", entry); err != nil {
			return err
		}
	}
	for _, path := range []string{filepath.Dir(destination), filepath.Dir(staged)} {
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		err = f.Sync()
		f.Close()
		if err != nil {
			return err
		}
	}
	return nil
}

func syncNativeDirectories(path, root string) error {
	for {
		f, err := os.Open(path)
		if err != nil {
			return err
		}
		err = f.Sync()
		f.Close()
		if err != nil {
			return err
		}
		if filepath.Clean(path) == filepath.Clean(root) {
			return nil
		}
		if filepath.Dir(path) == path {
			return fmt.Errorf("native staging root mismatch")
		}
		path = filepath.Dir(path)
	}
}
