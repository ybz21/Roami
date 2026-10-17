package metadb

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"golang.org/x/sys/unix"
	"gopkg.in/yaml.v3"
)

const LayoutVersion = 1

type Paths struct {
	Home     string `json:"homeRoot"`
	Data     string `json:"dataRoot"`
	Database string `json:"databaseRoot"`
	Backup   string `json:"backupRoot"`
}
type Layout struct {
	Version  int    `json:"layoutVersion"`
	Instance string `json:"instanceId"`
	Paths    Paths  `json:"paths"`
}
type DatabaseDescriptor struct {
	State string `json:"state"`
	ID    string `json:"id"`
	Kind  string `json:"kind"`
	Path  string `json:"path"`
	Owner string `json:"owner"`
}
type Catalog struct {
	Version   int                  `json:"layoutVersion"`
	Instance  string               `json:"instanceId"`
	DataRoot  string               `json:"ownerDataRoot"`
	Databases []DatabaseDescriptor `json:"databases"`
}

func ResolvePaths(home, data string) (Paths, error) {
	userHome, _ := os.UserHomeDir()
	defaultHome := firstPath(os.Getenv("ROAMI_HOME"), os.Getenv("ROAM_HOME"), os.Getenv("TTMUX_HOME"), filepath.Join(userHome, ".roami"))
	// Stores handed an explicit instance root must not inherit another instance's overrides.
	if home != "" && home == data {
		var l Layout
		if b, e := os.ReadFile(filepath.Join(data, "storage-layout.json")); e == nil && json.Unmarshal(b, &l) == nil && l.Paths.Data == data && l.Paths.Home != "" {
			home = l.Paths.Home
		}
	}
	explicitInstance := home != "" && filepath.Clean(home) != filepath.Clean(defaultHome)
	envPath := func(keys ...string) string {
		if explicitInstance {
			return ""
		}
		var values []string
		for _, key := range keys {
			values = append(values, os.Getenv(key))
		}
		return firstPath(values...)
	}

	if home == "" {
		u, e := os.UserHomeDir()
		if e != nil {
			return Paths{}, e
		}
		home = firstPath(os.Getenv("ROAMI_HOME"), os.Getenv("ROAM_HOME"), os.Getenv("TTMUX_HOME"), filepath.Join(u, ".roami"))
	}
	if data == "" {
		data = firstPath(envPath("ROAMI_DATA", "ROAM_DATA", "TTMUX_DATA"), home)
	}
	p := Paths{Home: home, Data: data}
	cfg := firstPath(envPath("ROAMI_CONFIG", "ROAM_CONFIG"), filepath.Join(home, "config.yaml"))
	var c struct {
		Storage struct {
			Data     string `yaml:"data_dir"`
			Database string `yaml:"database_dir"`
			Backup   string `yaml:"backup_dir"`
		} `yaml:"storage"`
	}
	if envPath("ROAMI_DATA") == "" || envPath("ROAMI_DATABASE_DIR") == "" || envPath("ROAMI_BACKUP_DIR") == "" {
		if b, e := os.ReadFile(cfg); e == nil {
			if e = yaml.Unmarshal(b, &c); e != nil {
				return p, e
			}
		} else if !os.IsNotExist(e) {
			return p, e
		}
	}
	configPath := func(s string) string {
		if s != "" && !filepath.IsAbs(s) {
			return filepath.Join(filepath.Dir(cfg), s)
		}
		return s
	}
	if data == home && envPath("ROAMI_DATA", "ROAM_DATA", "TTMUX_DATA") == "" && c.Storage.Data != "" {
		p.Data = configPath(c.Storage.Data)
	}
	p.Database = firstPath(envPath("ROAMI_DATABASE_DIR"), configPath(c.Storage.Database), filepath.Join(p.Data, "database"))
	p.Backup = firstPath(envPath("ROAMI_BACKUP_DIR"), configPath(c.Storage.Backup), filepath.Join(p.Data, "backups"))
	for _, v := range []*string{&p.Home, &p.Data, &p.Database, &p.Backup} {
		if strings.HasPrefix(*v, "~/") {
			u, _ := os.UserHomeDir()
			*v = filepath.Join(u, (*v)[2:])
		}
		a, e := filepath.Abs(*v)
		if e != nil {
			return p, e
		}
		*v = filepath.Clean(a)
	}
	return p, nil
}
func firstPath(values ...string) string {
	for _, v := range values {
		if v != "" {
			return v
		}
	}
	return ""
}

// Lock files are persistent: unlinking a held file would split the lock domain.
func (p Paths) Lock(name string, exclusive bool) (func(), error) {
	if name != "storage" && name != "catalog" {
		return nil, fmt.Errorf("invalid lock name")
	}
	dir := filepath.Join(p.Data, "locks")
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, err
	}
	f, e := os.OpenFile(filepath.Join(dir, name+".lock"), os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		return nil, e
	}
	how := unix.LOCK_SH
	if exclusive {
		how = unix.LOCK_EX
	}
	if name != "catalog" {
		how |= unix.LOCK_NB
	}
	if e = unix.Flock(int(f.Fd()), how); e != nil {
		f.Close()
		return nil, fmt.Errorf("STORAGE_BUSY: %s lock: %w", name, e)
	}
	return func() { _ = unix.Flock(int(f.Fd()), unix.LOCK_UN); _ = f.Close() }, nil
}
func atomicJSON(path string, value any) error {
	if e := os.MkdirAll(filepath.Dir(path), 0700); e != nil {
		return e
	}
	b, e := json.MarshalIndent(value, "", "  ")
	if e != nil {
		return e
	}
	f, e := os.CreateTemp(filepath.Dir(path), ".roami-*")
	if e != nil {
		return e
	}
	defer os.Remove(f.Name())
	if _, e = f.Write(b); e != nil {
		f.Close()
		return e
	}
	if e = f.Sync(); e != nil {
		f.Close()
		return e
	}
	if e = f.Close(); e != nil {
		return e
	}
	if e = os.Rename(f.Name(), path); e != nil {
		return e
	}
	d, e := os.Open(filepath.Dir(path))
	if e != nil {
		return e
	}
	defer d.Close()
	return d.Sync()
}
func (p Paths) ReadLayout() (Layout, error) {
	if _, err := os.Stat(filepath.Join(p.Data, "storage-migration.json")); err == nil {
		return Layout{}, fmt.Errorf("STORAGE_RECOVERY_REQUIRED: roami db migrate --recover")
	}
	var l Layout
	b, e := os.ReadFile(filepath.Join(p.Data, "storage-layout.json"))
	if e != nil {
		return l, e
	}
	e = json.Unmarshal(b, &l)
	if e == nil && (l.Version != LayoutVersion || l.Paths.Data != p.Data || l.Paths.Database != p.Database) {
		e = fmt.Errorf("STORAGE_LAYOUT_CONFLICT: use roami db migrate --layout")
	}
	if e == nil {
		c, ce := p.Catalog()
		if ce != nil {
			return l, ce
		}
		if c.Instance != l.Instance {
			return l, fmt.Errorf("STORAGE_INSTANCE_CONFLICT")
		}
	}
	return l, e
}

func (p Paths) Ensure() (Layout, error) {
	if l, e := p.ReadLayout(); e == nil {
		return l, nil
	} else if !os.IsNotExist(e) {
		return l, e
	}
	unlock, e := p.Lock("storage", true)
	if e != nil {
		return Layout{}, e
	}
	defer unlock()
	if l, e := p.ReadLayout(); e == nil {
		return l, nil
	} else if !os.IsNotExist(e) {
		return l, e
	}
	for _, legacy := range []string{filepath.Join(p.Home, "meta.db"), filepath.Join(p.Data, "ai-footprints.db")} {
		if _, e := os.Stat(legacy); e == nil {
			return Layout{}, fmt.Errorf("STORAGE_MIGRATION_REQUIRED: %s; run roami db migrate --layout --dry-run", legacy)
		}
	}

	if entries, e := os.ReadDir(p.Database); e == nil && len(entries) > 0 {
		return Layout{}, fmt.Errorf("STORAGE_LAYOUT_CONFLICT: database directory already contains data")
	}
	random := make([]byte, 16)
	if _, e = rand.Read(random); e != nil {
		return Layout{}, e
	}
	l := Layout{Version: LayoutVersion, Instance: hex.EncodeToString(random), Paths: p}
	if e = os.MkdirAll(filepath.Dir(p.Database), 0700); e != nil {
		return l, e
	}
	stage, e := os.MkdirTemp(filepath.Dir(p.Database), ".database-init-*")
	if e != nil {
		return l, e
	}
	if e = atomicJSON(filepath.Join(stage, "catalog.json"), Catalog{Version: LayoutVersion, Instance: l.Instance, DataRoot: p.Data}); e != nil {
		os.RemoveAll(stage)
		return l, e
	}
	return l, publishLayout(p, stage, l)

}
func (p Paths) Catalog() (Catalog, error) {
	var c Catalog
	b, e := os.ReadFile(filepath.Join(p.Database, "catalog.json"))
	if e != nil {
		return c, e
	}
	e = json.Unmarshal(b, &c)
	if e == nil && (c.DataRoot != p.Data || c.Version != LayoutVersion || c.Instance == "") {
		e = fmt.Errorf("STORAGE_INSTANCE_CONFLICT")
	}
	return c, e
}
func (p Paths) Register(d DatabaseDescriptor) error {
	release, e := p.Lock("storage", false)
	if e != nil {
		return e
	}
	defer release()
	return p.register(d)
}
func (p Paths) register(d DatabaseDescriptor) error {
	release, e := p.Lock("catalog", true)
	if e != nil {
		return e
	}
	defer release()
	rel, e := filepath.Rel(p.Database, d.Path)
	if e != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) || filepath.IsAbs(rel) {
		return fmt.Errorf("database outside instance root")
	}
	d.Path = filepath.ToSlash(rel)
	c, e := p.Catalog()
	if e != nil {
		return e
	}
	for _, existing := range c.Databases {
		if existing.ID == d.ID {
			oldIdentity, newIdentity := existing, d
			oldIdentity.State = ""
			newIdentity.State = ""
			if oldIdentity != newIdentity {
				return fmt.Errorf("catalog ID conflict: %s", d.ID)
			}
			if existing.State != d.State {
				for i := range c.Databases {
					if c.Databases[i].ID == d.ID {
						c.Databases[i].State = d.State
					}
				}
				return atomicJSON(filepath.Join(p.Database, "catalog.json"), c)
			}
			return nil
		}
		if existing.Path == d.Path {
			return fmt.Errorf("catalog path conflict: %s", d.Path)
		}
	}
	c.Databases = append(c.Databases, d)
	return atomicJSON(filepath.Join(p.Database, "catalog.json"), c)
}
func (p Paths) MainPath() string { return filepath.Join(p.Database, "meta.db") }
func (p Paths) SwarmPath(id string) string {
	return filepath.Join(p.Database, "swarms", id, "swarm.db")
}
func (p Paths) ArchivePath() string { return filepath.Join(p.Database, "archive", "ai-footprints.db") }

func (p Paths) MarkArchived(id string) error {
	release, e := p.Lock("storage", false)
	if e != nil {
		return e
	}
	defer release()
	releaseCatalog, e := p.Lock("catalog", true)
	if e != nil {
		return e
	}
	defer releaseCatalog()
	c, e := p.Catalog()
	if e != nil {
		return e
	}
	for i := range c.Databases {
		if c.Databases[i].ID == id {
			c.Databases[i].State = "archived"
			return atomicJSON(filepath.Join(p.Database, "catalog.json"), c)
		}
	}
	return nil
}
