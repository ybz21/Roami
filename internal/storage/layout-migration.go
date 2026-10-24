package metadb

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

type LayoutPlan struct {
	Source    *Paths               `json:"source,omitempty"`
	Paths     Paths                `json:"target"`
	Databases []DatabaseDescriptor `json:"databases"`
	Legacy    bool                 `json:"legacy"`
}
type layoutJournal struct {
	NativeStage     string                `json:"nativeStage,omitempty"`
	NativeFiles     []NativeBackupEntry   `json:"nativeFiles,omitempty"`
	Layout          Layout                `json:"layout"`
	Stage           string                `json:"stage"`
	ArtifactVerify  bool                  `json:"artifactVerify,omitempty"`
	ArtifactRestore bool                  `json:"artifactRestore,omitempty"`
	Artifacts       []ArtifactBackupEntry `json:"artifacts,omitempty"`
	ArtifactStage   string                `json:"artifactStage,omitempty"`
}

func PlanLayout(p Paths) (LayoutPlan, error) {
	plan := LayoutPlan{Paths: p, Legacy: true}
	b, readError := os.ReadFile(filepath.Join(p.Data, "storage-layout.json"))
	if readError == nil {
		var e error
		var l Layout
		if e = json.Unmarshal(b, &l); e != nil {
			return plan, e
		}
		if l.Version != LayoutVersion {
			return plan, fmt.Errorf("unsupported source layout version")
		}
		old := l.Paths
		c, e := old.Catalog()
		if e != nil {
			return plan, e
		}
		if c.Instance != l.Instance {
			return plan, fmt.Errorf("source layout instance mismatch")
		}
		plan.Source = &old
		for _, d := range c.Databases {
			if filepath.IsAbs(d.Path) || d.Path == "" || startsParent(d.Path) || d.Path == ".." {
				return plan, fmt.Errorf("invalid source database path")
			}
			d.Path = filepath.Join(old.Database, d.Path)
			plan.Databases = append(plan.Databases, d)
		}
		plan.Legacy = false
		return plan, nil
	}
	if !os.IsNotExist(readError) {
		return plan, readError
	}
	if _, e := os.Stat(filepath.Join(p.Home, "meta.db")); e == nil {
		plan.Databases = append(plan.Databases, DatabaseDescriptor{ID: "main", Kind: "main", Path: filepath.Join(p.Home, "meta.db"), Owner: "core"})
	}
	matches, e := filepath.Glob(filepath.Join(p.Home, "swarms", "*", "swarm.db"))
	if e != nil {
		return plan, e
	}
	for _, path := range matches {
		plan.Databases = append(plan.Databases, DatabaseDescriptor{ID: "swarm:" + filepath.Base(filepath.Dir(path)), Kind: "swarm", Path: path, Owner: "swarm"})
	}
	if _, e := os.Stat(filepath.Join(p.Data, "ai-footprints.db")); e == nil {
		plan.Databases = append(plan.Databases, DatabaseDescriptor{ID: "git-archive", Kind: "archive", Path: filepath.Join(p.Data, "ai-footprints.db"), Owner: "git-archive"})
	}
	return plan, nil
}
func destination(p Paths, d DatabaseDescriptor) string {
	switch d.Kind {
	case "main":
		return p.MainPath()
	case "swarm":
		return p.SwarmPath(filepath.Base(filepath.Dir(d.Path)))
	case "archive":
		return p.ArchivePath()
	default:
		return filepath.Join(p.Database, d.Path)
	}
}
func (p Paths) RecoverLayout() error {
	release, e := p.Lock("storage", true)
	if e != nil {
		return e
	}
	defer release()
	var j layoutJournal
	b, e := os.ReadFile(filepath.Join(p.Data, "storage-migration.json"))
	if e != nil {
		return e
	}
	if e = json.Unmarshal(b, &j); e != nil {
		return e
	}
	if j.Layout.Paths != p {
		return fmt.Errorf("migration journal targets another instance")
	}
	if _, e = os.Stat(p.Database); os.IsNotExist(e) {
		if e = os.Rename(j.Stage, p.Database); e != nil {
			return e
		}
	}
	c, e := p.Catalog()
	if e != nil {
		return e
	}
	if c.Instance != j.Layout.Instance {
		return fmt.Errorf("recovery instance mismatch")
	}
	if e = finishNativeRestore(p, j); e != nil {
		return e
	}
	if e = finishArtifactRestore(p, j); e != nil {
		return e
	}
	if e = atomicJSON(filepath.Join(p.Data, "storage-layout.json"), j.Layout); e != nil {
		return e
	}
	return os.Remove(filepath.Join(p.Data, "storage-migration.json"))
}
func publishLayout(p Paths, stage string, l Layout, artifacts ...artifactRestorePlan) error {
	journal := filepath.Join(p.Data, "storage-migration.json")
	j := layoutJournal{Layout: l, Stage: stage}
	if len(artifacts) > 0 {
		j.ArtifactVerify = artifacts[0].VerifyOnly
		// Older binaries must reject in-place verification rather than skip it.
		j.ArtifactRestore = true
		j.Artifacts = artifacts[0].Files
		j.ArtifactStage = artifacts[0].Stage
		j.NativeStage = artifacts[0].NativeStage
		j.NativeFiles = artifacts[0].NativeFiles
	}
	if e := atomicJSON(journal, j); e != nil {
		return e
	}
	if e := os.Rename(stage, p.Database); e != nil {
		return e
	}
	if e := finishNativeRestore(p, j); e != nil {
		return e
	}
	if e := finishArtifactRestore(p, j); e != nil {
		return e
	}
	if e := atomicJSON(filepath.Join(p.Data, "storage-layout.json"), l); e != nil {
		return e
	}
	return os.Remove(journal)
}
func (p Paths) RestoreSet(source string) error {
	release, e := p.Lock("storage", true)
	if e != nil {
		return e
	}
	defer release()
	if _, e = os.Lstat(filepath.Join(p.Data, "storage-migration.json")); !os.IsNotExist(e) {
		return fmt.Errorf("restore requires no pending migration; recover it first")
	}
	m, c, e := ValidateBackup(source)
	if e != nil {
		return e
	}
	if _, e = os.Stat(p.Database); !os.IsNotExist(e) {
		return fmt.Errorf("restore requires an absent database destination")
	}
	if _, e = os.Stat(filepath.Join(p.Data, "storage-layout.json")); !os.IsNotExist(e) {
		return fmt.Errorf("restore requires an empty instance")
	}
	if m.Version >= 2 {
		if _, e = os.Lstat(filepath.Join(p.Data, "agent-artifacts")); !os.IsNotExist(e) {
			return fmt.Errorf("restore requires an absent artifact destination")
		}
	}
	if e = os.MkdirAll(filepath.Dir(p.Database), 0700); e != nil {
		return e
	}
	stage, e := os.MkdirTemp(filepath.Dir(p.Database), ".database-restore-*")
	if e != nil {
		return e
	}
	artifactPlan := artifactRestorePlan{}
	published := false
	defer func() {
		if !published {
			os.RemoveAll(stage)
			if artifactPlan.Stage != "" {
				os.RemoveAll(artifactPlan.Stage)
			}
			if artifactPlan.NativeStage != "" {
				os.RemoveAll(artifactPlan.NativeStage)
			}
		}
	}()
	for _, d := range c.Databases {
		if e = snapshot(filepath.Join(source, d.Path), filepath.Join(stage, d.Path)); e != nil {
			return e
		}
	}
	if m.Version >= 2 {
		fileStage, stageErr := os.MkdirTemp(p.Data, ".agent-artifacts-restore-*")
		if stageErr != nil {
			return stageErr
		}
		artifactPlan = artifactRestorePlan{Stage: fileStage, Files: m.Artifacts}
		if e = os.MkdirAll(filepath.Join(fileStage, "agent-artifacts"), 0700); e != nil {
			return e
		}
		for _, entry := range m.Artifacts {
			if e = transferArtifact(filepath.Join(source, "files"), fileStage, entry); e != nil {
				return e
			}
		}
		fileStageDir, openErr := os.Open(fileStage)
		if openErr != nil {
			return openErr
		}
		e = fileStageDir.Sync()
		fileStageDir.Close()
		if e != nil {
			return e
		}
	}
	if m.Version == 3 {
		if _, e = os.Lstat(filepath.Join(p.Home, "agents", "native")); !os.IsNotExist(e) {
			return fmt.Errorf("restore requires an absent native destination")
		}
		nativeStage, err := os.MkdirTemp(p.Home, ".native-session-restore-*")
		if err != nil {
			return err
		}
		artifactPlan.NativeStage = nativeStage
		artifactPlan.NativeFiles = m.NativeFiles
		if e = os.MkdirAll(filepath.Join(nativeStage, "agents", "native"), 0700); e != nil {
			return e
		}
		if e = syncNativeDirectories(filepath.Join(nativeStage, "agents", "native"), nativeStage); e != nil {
			return e
		}
		for _, entry := range m.NativeFiles {
			if e = transferNativeFile(filepath.Join(source, "native-files"), nativeStage, entry); e != nil {
				return e
			}
		}
	}
	c.DataRoot = p.Data
	m.Layout.Paths = p
	if e = atomicJSON(filepath.Join(stage, "catalog.json"), c); e != nil {
		return e
	}
	// Once the durable journal exists, leave staging for --recover after interruption.
	published = true
	if m.Version >= 2 {
		return publishLayout(p, stage, m.Layout, artifactPlan)
	}
	return publishLayout(p, stage, m.Layout)
}
func (p Paths) MigrateLayout(offline bool) error {
	if !offline {
		return fmt.Errorf("stop all legacy writers, then use --offline; inspect with --layout --dry-run first")
	}
	release, e := p.Lock("storage", true)
	if e != nil {
		return e
	}
	defer release()
	if _, e = os.Stat(filepath.Join(p.Data, "storage-migration.json")); e == nil {
		return fmt.Errorf("interrupted migration: use roami db migrate --recover")
	}
	plan, e := PlanLayout(p)
	if e != nil {
		return e
	}
	if plan.Source != nil && filepath.Clean(plan.Source.Data) != filepath.Clean(p.Data) {
		return fmt.Errorf("data-root relocation requires backup and restore into an empty instance")
	}
	if !plan.Legacy {
		l, e := p.ReadLayout()
		if e == nil && l.Paths == p {
			return nil
		}
	}
	if _, e = os.Stat(p.Database); !os.IsNotExist(e) {
		return fmt.Errorf("target database directory already exists; refusing to overwrite")
	}
	if len(plan.Databases) == 0 {
		return fmt.Errorf("no legacy databases found; use roami db migrate to initialize a new instance")
	}
	if e = os.MkdirAll(filepath.Dir(p.Database), 0700); e != nil {
		return e
	}
	stage, e := os.MkdirTemp(filepath.Dir(p.Database), ".database-migrate-*")
	if e != nil {
		return e
	}
	keep := false
	defer func() {
		if !keep {
			os.RemoveAll(stage)
		}
	}()
	backup := filepath.Join(p.Backup, "pre-layout-"+time.Now().UTC().Format("20060102T150405.000000000"))
	if e = os.MkdirAll(backup, 0700); e != nil {
		return e
	}
	instance := filepath.Base(backup)
	if !plan.Legacy {
		var previous Layout
		b, e := os.ReadFile(filepath.Join(p.Data, "storage-layout.json"))
		if e != nil {
			return e
		}
		if e = json.Unmarshal(b, &previous); e != nil {
			return e
		}
		instance = previous.Instance
	}
	l := Layout{Version: LayoutVersion, Instance: instance, Paths: p}
	c := Catalog{Version: LayoutVersion, Instance: l.Instance, DataRoot: p.Data}
	manifest := BackupManifest{Version: 1, Layout: l, Created: time.Now().UTC().Format(time.RFC3339Nano)}
	for _, d := range plan.Databases {
		target := destination(p, d)
		if plan.Source != nil {
			sourceRelative, relativeError := filepath.Rel(plan.Source.Database, d.Path)
			if relativeError != nil || startsParent(sourceRelative) || sourceRelative == ".." || filepath.IsAbs(sourceRelative) {
				return fmt.Errorf("invalid source database destination")
			}
			target = filepath.Join(p.Database, sourceRelative)
		}
		rel, e := filepath.Rel(p.Database, target)
		if e != nil || startsParent(rel) {
			return fmt.Errorf("invalid migration destination")
		}
		if e = snapshot(d.Path, filepath.Join(backup, rel)); e != nil {
			return e
		}
		if e = snapshot(filepath.Join(backup, rel), filepath.Join(stage, rel)); e != nil {
			return e
		}
		d.Path = filepath.ToSlash(rel)
		if d.State == "" {
			d.State = "ready"
		}
		c.Databases = append(c.Databases, d)
		hash, e := fileHash(filepath.Join(backup, rel))
		if e != nil {
			return e
		}
		version, versionError := snapshotSchemaVersion(filepath.Join(backup, rel))
		if versionError != nil {
			return versionError
		}
		manifest.Databases = append(manifest.Databases, BackupEntry{DatabaseDescriptor: d, SHA256: hash, SchemaVersion: version})
	}
	artifactPlan, artifactError := backupLayoutArtifacts(p.Data, backup, &manifest)
	if artifactError != nil {
		return artifactError
	}
	if e = backupNativeFiles(p.Home, backup, &manifest); e != nil {
		return e
	}
	if e = atomicJSON(filepath.Join(backup, "catalog.json"), c); e != nil {
		return e
	}
	if e = atomicJSON(filepath.Join(backup, "storage-layout.json"), l); e != nil {
		return e
	}
	if e = atomicJSON(filepath.Join(backup, "manifest.json"), manifest); e != nil {
		return e
	}
	if _, _, e = ValidateBackup(backup); e != nil {
		return e
	}
	// Main schema changes happen only in the staged copy, after a recoverable backup.
	for _, d := range c.Databases {
		if d.Kind == "main" {
			path := filepath.Join(stage, d.Path)
			if _, e = OpenFile(path, mainSteps, Options{HomeDir: p.Home, DataDir: p.Data, BackupDir: backup}); e != nil {
				return e
			}
			if e = Discard(path); e != nil {
				return e
			}
		}
	}
	if e = atomicJSON(filepath.Join(stage, "catalog.json"), c); e != nil {
		return e
	}
	keep = true
	if artifactPlan.VerifyOnly {
		return publishLayout(p, stage, l, artifactPlan)
	}
	return publishLayout(p, stage, l)
}
