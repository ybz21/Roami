package metadb

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

type artifactRestorePlan struct {
	NativeStage string
	NativeFiles []NativeBackupEntry
	VerifyOnly  bool
	Stage       string
	Files       []ArtifactBackupEntry
}

type ArtifactBackupEntry struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"sizeBytes"`
}

var artifactDigest = regexp.MustCompile(`^[0-9a-f]{64}$`)

func artifactBlobPath(digest string) string {
	return "agent-artifacts/blobs/" + digest[:2] + "/" + digest + ".blob"
}

// The Python snapshot remains the source of truth; Go only transports its referenced files.
func indexedArtifacts(root string, databases []BackupEntry) ([]ArtifactBackupEntry, bool, error) {
	files := map[string]ArtifactBackupEntry{}
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
		err = db.QueryRow("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='artifacts'").Scan(&exists)
		if err != nil {
			db.Close()
			return nil, false, err
		}
		if exists == 0 {
			db.Close()
			continue
		}
		present = true
		rows, err := db.Query("SELECT path,sha256,size_bytes FROM artifacts WHERE deleted_ms IS NULL")
		if err != nil {
			db.Close()
			return nil, false, err
		}
		for rows.Next() {
			var entry ArtifactBackupEntry
			if err = rows.Scan(&entry.Path, &entry.SHA256, &entry.Size); err != nil {
				break
			}
			if !artifactDigest.MatchString(entry.SHA256) || entry.Size < 0 || entry.Size > 512*1024*1024 || entry.Path != artifactBlobPath(entry.SHA256) {
				err = fmt.Errorf("invalid artifact index in %s", descriptor.ID)
				break
			}
			if previous, ok := files[entry.Path]; ok && previous != entry {
				err = fmt.Errorf("conflicting artifact metadata")
				break
			}
			files[entry.Path] = entry
		}
		if err == nil {
			err = rows.Err()
		}
		rows.Close()
		db.Close()
		if err != nil {
			return nil, false, err
		}
	}
	result := make([]ArtifactBackupEntry, 0, len(files))
	for _, entry := range files {
		result = append(result, entry)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].Path < result[j].Path })
	return result, present, nil
}

func openArtifact(root string, entry ArtifactBackupEntry) (*os.File, error) {
	if !artifactDigest.MatchString(entry.SHA256) || entry.Path != artifactBlobPath(entry.SHA256) || entry.Size < 0 || entry.Size > 512*1024*1024 {
		return nil, fmt.Errorf("invalid artifact manifest entry")
	}
	path := root
	for _, component := range []string{"agent-artifacts", "blobs", entry.SHA256[:2], entry.SHA256 + ".blob"} {
		path = filepath.Join(path, component)
		info, err := os.Lstat(path)
		if err != nil {
			return nil, err
		}
		if info.Mode()&os.ModeSymlink != 0 {
			return nil, fmt.Errorf("artifact symlink is unsupported")
		}
		if component == entry.SHA256+".blob" && !info.Mode().IsRegular() {
			return nil, fmt.Errorf("invalid artifact file")
		}
		if component != entry.SHA256+".blob" && !info.IsDir() {
			return nil, fmt.Errorf("invalid artifact directory")
		}
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	info, err := file.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() != entry.Size {
		file.Close()
		return nil, fmt.Errorf("artifact size or file type mismatch")
	}
	return file, nil
}

func transferArtifact(source, destination string, entry ArtifactBackupEntry) error {
	input, err := openArtifact(source, entry)
	if err != nil {
		return err
	}
	defer input.Close()
	var output *os.File
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
	}
	hash := sha256.New()
	var writer io.Writer = hash
	if output != nil {
		writer = io.MultiWriter(hash, output)
	}
	size, err := io.Copy(writer, io.LimitReader(input, entry.Size+1))
	if err != nil {
		return err
	}
	if size != entry.Size || hex.EncodeToString(hash.Sum(nil)) != entry.SHA256 {
		return fmt.Errorf("artifact checksum failed")
	}
	if output != nil {
		if err = output.Chmod(0400); err != nil {
			return err
		}
		if err = output.Sync(); err != nil {
			return err
		}
		for directory := filepath.Dir(output.Name()); ; directory = filepath.Dir(directory) {
			file, openErr := os.Open(directory)
			if openErr != nil {
				return openErr
			}
			syncErr := file.Sync()
			file.Close()
			if syncErr != nil {
				return syncErr
			}
			if filepath.Clean(directory) == filepath.Clean(destination) {
				break
			}
		}
		return nil
	}
	return nil
}

func finishArtifactRestore(p Paths, journal layoutJournal) error {
	if journal.ArtifactVerify {
		if !journal.ArtifactRestore || journal.ArtifactStage != "" {
			return fmt.Errorf("conflicting artifact publication mode")
		}
		for _, entry := range journal.Artifacts {
			if err := transferArtifact(p.Data, "", entry); err != nil {
				return err
			}
		}
		return nil
	}
	if !journal.ArtifactRestore {
		return nil
	}
	if filepath.Dir(journal.ArtifactStage) != p.Data || !strings.HasPrefix(filepath.Base(journal.ArtifactStage), ".agent-artifacts-restore-") {
		return fmt.Errorf("invalid artifact restore staging path")
	}
	stageInfo, err := os.Lstat(journal.ArtifactStage)
	if err != nil || !stageInfo.IsDir() {
		return fmt.Errorf("artifact restore staging directory missing")
	}
	staged := filepath.Join(journal.ArtifactStage, "agent-artifacts")
	destination := filepath.Join(p.Data, "agent-artifacts")
	sourceInfo, sourceErr := os.Lstat(staged)
	info, targetErr := os.Lstat(destination)
	if sourceErr == nil {
		if !sourceInfo.IsDir() {
			return fmt.Errorf("invalid artifact restore directory")
		}
		if !os.IsNotExist(targetErr) {
			return fmt.Errorf("artifact restore destination conflict")
		}
		if err := os.Rename(staged, destination); err != nil {
			return err
		}
	} else if !os.IsNotExist(sourceErr) || targetErr != nil || !info.IsDir() {
		return fmt.Errorf("artifact restore staging is missing")
	}
	for _, entry := range journal.Artifacts {
		if err := transferArtifact(p.Data, "", entry); err != nil {
			return err
		}
	}
	for _, directory := range []string{p.Data, filepath.Dir(staged)} {
		file, err := os.Open(directory)
		if err != nil {
			return err
		}
		err = file.Sync()
		file.Close()
		if err != nil {
			return err
		}
	}
	return nil
}
