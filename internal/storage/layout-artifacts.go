package metadb

import (
	"database/sql"
	"fmt"
	"path/filepath"
)

func snapshotSchemaVersion(path string) (int, error) {
	database, err := sql.Open("sqlite", "file:"+path+"?mode=ro")
	if err != nil {
		return 0, err
	}
	defer database.Close()
	var check string
	if err = database.QueryRow("PRAGMA integrity_check").Scan(&check); err != nil || check != "ok" {
		return 0, fmt.Errorf("invalid migration snapshot")
	}
	var exists int
	if err = database.QueryRow("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='schema_meta'").Scan(&exists); err != nil {
		return 0, err
	}
	if exists == 0 {
		return 0, nil
	}
	var version int
	err = database.QueryRow("SELECT COALESCE(MAX(version),0) FROM schema_meta").Scan(&version)
	return version, err
}

func backupLayoutArtifacts(source, backup string, manifest *BackupManifest) (artifactRestorePlan, error) {
	files, present, err := indexedArtifacts(backup, manifest.Databases)
	if err != nil {
		return artifactRestorePlan{}, err
	}
	if !present {
		return artifactRestorePlan{}, nil
	}
	manifest.Version, manifest.Artifacts = 2, files
	for _, entry := range files {
		if err := transferArtifact(source, filepath.Join(backup, "files"), entry); err != nil {
			return artifactRestorePlan{}, fmt.Errorf("layout artifact backup: %w", err)
		}
	}
	return artifactRestorePlan{Files: files, VerifyOnly: true}, nil
}
