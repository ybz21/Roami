package metadb

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"
)

type LayoutPlan struct {
	Paths     Paths                `json:"target"`
	Databases []DatabaseDescriptor `json:"databases"`
	Legacy    bool                 `json:"legacy"`
}
type layoutJournal struct {
	Layout Layout `json:"layout"`
	Stage  string `json:"stage"`
}

func PlanLayout(p Paths) (LayoutPlan, error) {
	plan := LayoutPlan{Paths: p, Legacy: true}
	if b, e := os.ReadFile(filepath.Join(p.Data, "storage-layout.json")); e == nil {
		var l Layout
		if e = json.Unmarshal(b, &l); e != nil {
			return plan, e
		}
		old := l.Paths
		c, e := old.Catalog()
		if e != nil {
			return plan, e
		}
		for _, d := range c.Databases {
			d.Path = filepath.Join(old.Database, d.Path)
			plan.Databases = append(plan.Databases, d)
		}
		plan.Legacy = false
		return plan, nil
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
	if e = atomicJSON(filepath.Join(p.Data, "storage-layout.json"), j.Layout); e != nil {
		return e
	}
	return os.Remove(filepath.Join(p.Data, "storage-migration.json"))
}
func publishLayout(p Paths, stage string, l Layout) error {
	journal := filepath.Join(p.Data, "storage-migration.json")
	if e := atomicJSON(journal, layoutJournal{Layout: l, Stage: stage}); e != nil {
		return e
	}
	if e := os.Rename(stage, p.Database); e != nil {
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
	if e = os.MkdirAll(filepath.Dir(p.Database), 0700); e != nil {
		return e
	}
	stage, e := os.MkdirTemp(filepath.Dir(p.Database), ".database-restore-*")
	if e != nil {
		return e
	}
	published := false
	defer func() {
		if !published {
			os.RemoveAll(stage)
		}
	}()
	for _, d := range c.Databases {
		if e = snapshot(filepath.Join(source, d.Path), filepath.Join(stage, d.Path)); e != nil {
			return e
		}
	}
	c.DataRoot = p.Data
	m.Layout.Paths = p
	if e = atomicJSON(filepath.Join(stage, "catalog.json"), c); e != nil {
		return e
	}
	// Once the durable journal exists, leave staging for --recover after interruption.
	published = true
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
		manifest.Databases = append(manifest.Databases, BackupEntry{DatabaseDescriptor: d, SHA256: hash})
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
	return publishLayout(p, stage, l)
}
