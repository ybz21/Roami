package metadb

import (
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

const maxPythonAgentSchemaVersion = 10

type BackupEntry struct {
	DatabaseDescriptor
	SHA256        string `json:"sha256"`
	SchemaVersion int    `json:"schemaVersion"`
}
type BackupManifest struct {
	Version   int                   `json:"formatVersion"`
	Layout    Layout                `json:"layout"`
	Created   string                `json:"createdAt"`
	Databases []BackupEntry         `json:"databases"`
	Artifacts []ArtifactBackupEntry `json:"artifacts,omitempty"`
}

func fileHash(path string) (string, error) {
	f, e := os.Open(path)
	if e != nil {
		return "", e
	}
	defer f.Close()
	h := sha256.New()
	_, e = io.Copy(h, f)
	return hex.EncodeToString(h.Sum(nil)), e
}
func snapshot(source, dest string) error {
	if e := os.MkdirAll(filepath.Dir(dest), 0700); e != nil {
		return e
	}
	db, e := sql.Open("sqlite", "file:"+source+"?mode=ro&_pragma=busy_timeout(10000)")
	if e != nil {
		return e
	}
	defer db.Close()
	if _, e = db.Exec("VACUUM INTO ?", dest); e != nil {
		return e
	}
	return os.Chmod(dest, 0600)
}
func (p Paths) BackupSet(destination string) (string, error) {
	release, e := p.Lock("storage", true)
	if e != nil {
		return "", e
	}
	defer release()
	l, e := p.ReadLayout()
	if e != nil {
		return "", e
	}
	c, e := p.Catalog()
	if e != nil {
		return "", e
	}
	if destination == "" {
		destination = filepath.Join(p.Backup, time.Now().UTC().Format("20060102T150405.000000000"))
	}
	dest, e := filepath.Abs(destination)
	if e != nil {
		return "", e
	}
	if rel, e := filepath.Rel(p.Database, dest); e != nil || (rel != ".." && !startsParent(rel)) {
		return "", fmt.Errorf("backup destination must be outside database directory")
	}
	if _, e = os.Stat(dest); !os.IsNotExist(e) {
		return "", fmt.Errorf("backup destination already exists or cannot be accessed")
	}
	if e = os.MkdirAll(filepath.Dir(dest), 0700); e != nil {
		return "", e
	}
	stage, e := os.MkdirTemp(filepath.Dir(dest), ".roami-backup-*")
	if e != nil {
		return "", e
	}
	defer os.RemoveAll(stage)
	registered := map[string]bool{}
	for _, d := range c.Databases {
		registered[filepath.ToSlash(d.Path)] = true
	}
	if e = filepath.WalkDir(p.Database, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !entry.IsDir() && (strings.HasSuffix(path, ".db") || strings.HasSuffix(path, ".sqlite")) {
			rel, e := filepath.Rel(p.Database, path)
			if e != nil {
				return e
			}
			if !registered[filepath.ToSlash(rel)] {
				return fmt.Errorf("unregistered database: %s", rel)
			}
		}
		return nil
	}); e != nil {
		return "", e
	}
	manifest := BackupManifest{Version: 1, Layout: l, Created: time.Now().UTC().Format(time.RFC3339Nano)}
	for _, d := range c.Databases {
		if d.State != "ready" && d.State != "archived" {
			return "", fmt.Errorf("database %s is not ready", d.ID)
		}
		source := filepath.Join(p.Database, d.Path)
		target := filepath.Join(stage, d.Path)
		if e = snapshot(source, target); e != nil {
			return "", fmt.Errorf("snapshot %s: %w", d.ID, e)
		}
		db, err := sql.Open("sqlite", "file:"+target+"?mode=ro")
		if err != nil {
			return "", err
		}
		var check string
		err = db.QueryRow("PRAGMA integrity_check").Scan(&check)
		if err != nil || check != "ok" {
			db.Close()
			return "", fmt.Errorf("invalid snapshot %s: %s %v", d.ID, check, err)
		}
		var version int
		_ = db.QueryRow("SELECT COALESCE(MAX(version),0) FROM schema_meta").Scan(&version)
		db.Close()
		hash, err := fileHash(target)
		if err != nil {
			return "", err
		}
		manifest.Databases = append(manifest.Databases, BackupEntry{DatabaseDescriptor: d, SHA256: hash, SchemaVersion: version})
	}
	artifacts, present, e := indexedArtifacts(stage, manifest.Databases)
	if e != nil {
		return "", e
	}
	if present {
		manifest.Version = 2
		for _, entry := range artifacts {
			if e = transferArtifact(p.Data, filepath.Join(stage, "files"), entry); e != nil {
				return "", fmt.Errorf("backup artifact %s: %w", entry.SHA256, e)
			}
		}
	}
	manifest.Artifacts = artifacts
	if e = atomicJSON(filepath.Join(stage, "catalog.json"), c); e != nil {
		return "", e
	}
	if e = atomicJSON(filepath.Join(stage, "storage-layout.json"), l); e != nil {
		return "", e
	}
	if e = atomicJSON(filepath.Join(stage, "manifest.json"), manifest); e != nil {
		return "", e
	}
	if e = os.Rename(stage, dest); e != nil {
		return "", e
	}
	return dest, nil
}
func startsParent(rel string) bool { return len(rel) > 3 && rel[:3] == ".."+string(filepath.Separator) }

// ValidateBackup is also the precondition for an offline restore into an empty instance.
func ValidateBackup(path string) (BackupManifest, Catalog, error) {
	var m BackupManifest
	var c Catalog
	b, e := os.ReadFile(filepath.Join(path, "manifest.json"))
	if e != nil {
		return m, c, e
	}
	if e = json.Unmarshal(b, &m); e != nil {
		return m, c, e
	}
	if (m.Version != 1 && m.Version != 2) || m.Layout.Version != LayoutVersion {
		return m, c, fmt.Errorf("unsupported backup version")
	}
	b, e = os.ReadFile(filepath.Join(path, "catalog.json"))
	if e != nil {
		return m, c, e
	}
	if e = json.Unmarshal(b, &c); e != nil {
		return m, c, e
	}
	var saved Layout
	b, e = os.ReadFile(filepath.Join(path, "storage-layout.json"))
	if e != nil {
		return m, c, e
	}
	if e = json.Unmarshal(b, &saved); e != nil {
		return m, c, e
	}
	if saved != m.Layout {
		return m, c, fmt.Errorf("backup layout metadata mismatch")
	}
	if c.Instance != m.Layout.Instance || len(c.Databases) != len(m.Databases) {
		return m, c, fmt.Errorf("backup catalog mismatch")
	}
	for i, d := range m.Databases {
		if d.Kind == "main" && d.SchemaVersion > len(mainSteps) {
			return m, c, fmt.Errorf("backup main schema is newer than this binary")
		}
		if d.Kind == "agent" && (d.Owner != "python-agent" || d.SchemaVersion < 1 || d.SchemaVersion > maxPythonAgentSchemaVersion) {
			return m, c, fmt.Errorf("unsupported Agent schema or owner: %s", d.ID)
		}
		if d.DatabaseDescriptor != c.Databases[i] {
			return m, c, fmt.Errorf("backup descriptor mismatch")
		}
		target := filepath.Join(path, d.Path)
		rel, e := filepath.Rel(path, target)
		if e != nil || startsParent(rel) || rel == ".." || filepath.IsAbs(d.Path) {
			return m, c, fmt.Errorf("invalid backup path")
		}
		hash, e := fileHash(target)
		if e != nil || hash != d.SHA256 {
			return m, c, fmt.Errorf("backup checksum failed: %s", d.ID)
		}
	}
	indexed, present, err := indexedArtifacts(path, m.Databases)
	if err != nil {
		return m, c, err
	}
	if present && m.Version != 2 {
		return m, c, fmt.Errorf("Agent artifact backup package is incomplete")
	}
	if len(indexed) != len(m.Artifacts) {
		return m, c, fmt.Errorf("artifact manifest does not match database")
	}
	for i, entry := range indexed {
		if entry != m.Artifacts[i] {
			return m, c, fmt.Errorf("artifact manifest entry mismatch")
		}
		if err = transferArtifact(filepath.Join(path, "files"), "", entry); err != nil {
			return m, c, err
		}
	}
	return m, c, nil
}
