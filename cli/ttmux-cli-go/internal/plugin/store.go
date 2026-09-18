package plugin

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"ttmux-cli-go/internal/metadb"
	"ttmux-cli-go/internal/runtime"

	_ "modernc.org/sqlite"
)

// Env bundles the paths and runtime the plugin foundation needs. 配置与安装态
// 进 $TTMUX_HOME,运行态进 $TTMUX_DATA(见 docs/design/plugin/04 第 10 节)。
type Env struct {
	RT runtime.Runtime
}

func NewEnv(rt runtime.Runtime) Env { return Env{RT: rt} }

func (e Env) metaDBPath() string          { return filepath.Join(e.RT.HomeDir, "meta.db") }
func (e Env) DataDir() string             { return filepath.Join(e.RT.DataDir, "plugins") }
func (e Env) AuditDir() string            { return filepath.Join(e.DataDir(), "audit") }
func (e Env) LogsDir() string             { return filepath.Join(e.DataDir(), "logs") }
func (e Env) StorageDir(id string) string { return filepath.Join(e.DataDir(), "storage", id) }

// SockPath prefers $XDG_RUNTIME_DIR, falling back to $TTMUX_DATA/plugins/run.
func (e Env) SockPath() string {
	if dir := os.Getenv("XDG_RUNTIME_DIR"); dir != "" {
		return filepath.Join(dir, "ttmux", "plugin.sock")
	}
	return filepath.Join(e.DataDir(), "run", "plugin.sock")
}

// Store wraps the plugin tables in meta.db.
type Store struct {
	db  *metadb.DB
	env Env
}

// Open opens meta.db and ensures plugin tables + builtin registry rows exist.
func Open(env Env) (*Store, error) {
	for _, dir := range []string{env.RT.HomeDir, env.DataDir(), env.AuditDir(), env.LogsDir(), filepath.Dir(env.SockPath())} {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, err
		}
	}
	// schema 与迁移都在 internal/metadb 的版本链里（baseline 那一步建的
	// plugins / plugin_sessions / plugin_findings / plugin_notifications），
	// 开库即已就位——原先这里那两条「裸 ALTER 忽略错误」也一并收进去了。
	db, err := metadb.Open(env.RT.HomeDir, metadb.Options{DataDir: env.DataDir(), HomeDir: env.RT.HomeDir})
	if err != nil {
		return nil, err
	}
	return &Store{db: db, env: env}, nil
}

// Close 空转：库是 metadb 的进程级共享连接，plugind 长驻着它、sessmeta 也在用。
// 谁都不该因为自己用完了就把它关掉。真要释放走 metadb.Discard。
func (s *Store) Close() {}

func (s *Store) now() string { return s.env.RT.Now().Format(time.RFC3339) }

// ── registry ──

// RegisteredPlugin is a registry row joined with its parsed manifest.
type RegisteredPlugin struct {
	Manifest    Manifest `json:"manifest"`
	Enabled     bool     `json:"enabled"`
	Installed   string   `json:"installed"`
	InstallPath string   `json:"installPath,omitempty"` // 外部插件的文件位置(builtin 为空)
}

// SyncBuiltin upserts a builtin manifest into the registry. Builtin 官方插件
// 默认启用(信任层级 Built-in,见 02-product 治理分层)。
func (s *Store) SyncBuiltin(m Manifest) error {
	raw, err := json.Marshal(m)
	if err != nil {
		return err
	}
	res, err := s.db.Exec(`UPDATE plugins SET version=?, kind=?, manifest=? WHERE id=?`,
		m.Version, m.Runtime.Kind, string(raw), m.ID)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		_, err = s.db.Exec(`INSERT INTO plugins (id, version, kind, enabled, manifest, installed) VALUES (?,?,?,1,?,?)`,
			m.ID, m.Version, m.Runtime.Kind, string(raw), s.now())
	}
	return err
}

// InstallExternal registers an external (node/exec) plugin whose files live
// at installPath. 安装后默认不启用(02-product 用户旅程:授权发生在启用时)。
func (s *Store) InstallExternal(m Manifest, installPath string) error {
	raw, err := json.Marshal(m)
	if err != nil {
		return err
	}
	res, err := s.db.Exec(`UPDATE plugins SET version=?, kind=?, manifest=?, install_path=? WHERE id=?`,
		m.Version, m.Runtime.Kind, string(raw), installPath, m.ID)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		_, err = s.db.Exec(`INSERT INTO plugins (id, version, kind, enabled, manifest, installed, install_path) VALUES (?,?,?,0,?,?,?)`,
			m.ID, m.Version, m.Runtime.Kind, string(raw), s.now(), installPath)
	}
	return err
}

// migrateRenamedBuiltins settles builtin plugin renames(0.4.0 起
// roam.feishu-bridge 通用化为 roam.im-bridge):存储目录整体搬迁(config/
// kv 原样保留),注册行与会话归属改名,旧 id 不再残留。幂等,可反复调用。
func (s *Store) migrateRenamedBuiltins() {
	const oldID, newID = "roam.feishu-bridge", "roam.im-bridge"
	oldDir, newDir := s.env.StorageDir(oldID), s.env.StorageDir(newID)
	if _, err := os.Stat(oldDir); err == nil {
		if _, err := os.Stat(newDir); os.IsNotExist(err) {
			_ = os.Rename(oldDir, newDir)
		}
	}
	_, _ = s.db.Exec(`DELETE FROM plugins WHERE id=?`, oldID)
	_, _ = s.db.Exec(`UPDATE plugin_sessions SET plugin=? WHERE plugin=?`, newID, oldID)
}

// Remove deletes a plugin's registry row plus its owned rows in the session/
// finding/notification tables —— 卸载后不留孤儿数据(会话表按 plugin、通知表
// 按 source 归属)。安装文件与 storage 目录由调用方处理(见 uninstall)。
// 仅用于外部插件;内置插件走 SoftRemove(见其注释)。
func (s *Store) Remove(id string) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	for _, q := range []string{
		`DELETE FROM plugins WHERE id=?`,
		`DELETE FROM plugin_sessions WHERE plugin=?`,
		`DELETE FROM plugin_findings WHERE plugin=?`,
		`DELETE FROM plugin_notifications WHERE source=?`,
	} {
		if _, err := tx.Exec(q, id); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	return tx.Commit()
}

// SoftRemove tombstones a built-in plugin: 保留注册行(否则每次命令的
// SyncBuiltins 会把它 upsert 回来并重新启用),置 removed=1 + 禁用,并清掉
// 其名下的会话/finding/通知孤儿行。恢复见 Restore。
func (s *Store) SoftRemove(id string) error {
	tx, err := s.db.Begin()
	if err != nil {
		return err
	}
	for _, q := range []string{
		`UPDATE plugins SET removed=1, enabled=0 WHERE id=?`,
		`DELETE FROM plugin_sessions WHERE plugin=?`,
		`DELETE FROM plugin_findings WHERE plugin=?`,
		`DELETE FROM plugin_notifications WHERE source=?`,
	} {
		if _, err := tx.Exec(q, id); err != nil {
			_ = tx.Rollback()
			return err
		}
	}
	return tx.Commit()
}

// Restore clears a built-in tombstone(removed=0)并重新启用。manifest 已由
// 调用前的 SyncBuiltins 刷新,这里只翻状态。
func (s *Store) Restore(id string) error {
	_, err := s.db.Exec(`UPDATE plugins SET removed=0, enabled=1 WHERE id=?`, id)
	return err
}

// List returns registered plugins that are not soft-removed(正常展示用)。
func (s *Store) List() ([]RegisteredPlugin, error) {
	return s.query(`WHERE IFNULL(removed,0)=0`)
}

// Removed returns soft-removed built-in plugins awaiting restore(恢复入口用)。
func (s *Store) Removed() ([]RegisteredPlugin, error) {
	return s.query(`WHERE IFNULL(removed,0)=1`)
}

func (s *Store) query(where string) ([]RegisteredPlugin, error) {
	rows, err := s.db.Query(`SELECT manifest, enabled, IFNULL(installed,''), IFNULL(install_path,'') FROM plugins ` + where + ` ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []RegisteredPlugin
	for rows.Next() {
		var raw, installed, installPath string
		var enabled int
		if err := rows.Scan(&raw, &enabled, &installed, &installPath); err != nil {
			return nil, err
		}
		var m Manifest
		if err := json.Unmarshal([]byte(raw), &m); err != nil {
			continue // 损坏行不阻断列表
		}
		out = append(out, RegisteredPlugin{Manifest: m, Enabled: enabled == 1, Installed: installed, InstallPath: installPath})
	}
	return out, rows.Err()
}

// Get returns one plugin by id (or by short name), 含已软删的(恢复/卸载需要能定位)。
func (s *Store) Get(id string) (RegisteredPlugin, error) {
	all, err := s.query("")
	if err != nil {
		return RegisteredPlugin{}, err
	}
	for _, p := range all {
		if p.Manifest.ID == id || p.Manifest.Name == id {
			return p, nil
		}
	}
	return RegisteredPlugin{}, fmt.Errorf("plugin not found: %s", id)
}

// SetEnabled toggles a plugin.
func (s *Store) SetEnabled(id string, enabled bool) error {
	p, err := s.Get(id)
	if err != nil {
		return err
	}
	v := 0
	if enabled {
		v = 1
	}
	_, err = s.db.Exec(`UPDATE plugins SET enabled=? WHERE id=?`, v, p.Manifest.ID)
	return err
}

// FindCommand resolves a command to its enabled owner plugin。两种形式:
// 短名 "<name>.<cmd>"(CLI 手敲),与 id 限定 "<id>:<cmd>"(Web 按路由
// 插件 id 调用,精确归属——短名在多 publisher 撞名时会被最先匹配者接走)。
// 限定形式解析失败不回退短名:否则伪造 id 拼出的串仍可能撞上某个短名
// 恰好匹配的插件,归属又变得可混淆。
func (s *Store) FindCommand(commandID string) (RegisteredPlugin, string, error) {
	all, err := s.List()
	if err != nil {
		return RegisteredPlugin{}, "", err
	}
	pick := func(p RegisteredPlugin, handler string) (RegisteredPlugin, string, error) {
		if !p.Enabled {
			return RegisteredPlugin{}, "", fmt.Errorf("plugin %s is disabled (enable with: ttmux plugin enable %s)", p.Manifest.ID, p.Manifest.Name)
		}
		return p, handler, nil
	}
	if strings.Contains(commandID, ":") { // id 限定形式,只按全 id 精确解析
		for _, p := range all {
			if handler, ok := p.Manifest.FullCommandOwner(commandID); ok {
				return pick(p, handler)
			}
		}
	} else {
		for _, p := range all {
			if handler, ok := p.Manifest.CommandOwner(commandID); ok {
				return pick(p, handler)
			}
		}
	}
	return RegisteredPlugin{}, "", fmt.Errorf("unknown plugin command: %s", commandID)
}

// ── sessions (owner/labels 会话组句柄,见 04-architecture 2.5) ──

// SessionRow tracks a plugin-owned tmux session.
type SessionRow struct {
	Session string            `json:"session"`
	Plugin  string            `json:"plugin"`
	Job     string            `json:"job"`
	Labels  map[string]string `json:"labels"`
	Status  string            `json:"status"`
	Created string            `json:"created"`
}

func (s *Store) AddSession(row SessionRow) error {
	labels, _ := json.Marshal(row.Labels)
	_, err := s.db.Exec(`INSERT OR REPLACE INTO plugin_sessions (session, plugin, job, labels, status, created, updated)
		VALUES (?,?,?,?,?,?,?)`, row.Session, row.Plugin, row.Job, string(labels), "running", s.now(), s.now())
	return err
}

// MigrateSessionNames 会话改名成 id 后，把插件会话表里记的老会话名换掉
// （mapping = {老会话名: 新会话名}，来自 runtime.MigrateSessionsToID）。
func (s *Store) MigrateSessionNames(mapping map[string]string) {
	for old, neu := range mapping {
		_, _ = s.db.Exec(`UPDATE plugin_sessions SET session=?, updated=? WHERE session=?`, neu, s.now(), old)
	}
}

func (s *Store) UpdateSessionStatus(session, status string) error {
	_, err := s.db.Exec(`UPDATE plugin_sessions SET status=?, updated=? WHERE session=?`, status, s.now(), session)
	return err
}

// Sessions lists rows filtered by owner plugin (""=all) and/or status (""=all).
func (s *Store) Sessions(plugin, status string) ([]SessionRow, error) {
	rows, err := s.db.Query(`SELECT session, plugin, IFNULL(job,''), IFNULL(labels,'{}'), IFNULL(status,''), IFNULL(created,'')
		FROM plugin_sessions WHERE (?='' OR plugin=?) AND (?='' OR status=?) ORDER BY created`, plugin, plugin, status, status)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []SessionRow
	for rows.Next() {
		var r SessionRow
		var labels string
		if err := rows.Scan(&r.Session, &r.Plugin, &r.Job, &labels, &r.Status, &r.Created); err != nil {
			return nil, err
		}
		_ = json.Unmarshal([]byte(labels), &r.Labels)
		out = append(out, r)
	}
	return out, rows.Err()
}

// ── findings ──

// Finding is a structured review result (智能评审插件设计 §5 的最小子集).
type Finding struct {
	ID       int64  `json:"id"`
	Plugin   string `json:"plugin"`
	Job      string `json:"job"`
	Severity string `json:"severity"`
	Title    string `json:"title"`
	File     string `json:"file"`
	Line     int    `json:"line"`
	Detail   string `json:"detail"`
	Status   string `json:"status"`
	Created  string `json:"created"`
}

func (s *Store) CreateFinding(f Finding) (int64, error) {
	res, err := s.db.Exec(`INSERT INTO plugin_findings (plugin, job, severity, title, file, line, detail, status, created, updated)
		VALUES (?,?,?,?,?,?,?,?,?,?)`,
		f.Plugin, f.Job, f.Severity, f.Title, f.File, f.Line, f.Detail, orDefault(f.Status, "open"), s.now(), s.now())
	if err != nil {
		return 0, err
	}
	return res.LastInsertId()
}

// Findings lists findings filtered by plugin/job/status (""=all).
func (s *Store) Findings(plugin, job, status string) ([]Finding, error) {
	rows, err := s.db.Query(`SELECT id, plugin, IFNULL(job,''), severity, title, IFNULL(file,''), IFNULL(line,0), IFNULL(detail,''), status, IFNULL(created,'')
		FROM plugin_findings WHERE (?='' OR plugin=?) AND (?='' OR job=?) AND (?='' OR status=?) ORDER BY id`,
		plugin, plugin, job, job, status, status)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Finding
	for rows.Next() {
		var f Finding
		if err := rows.Scan(&f.ID, &f.Plugin, &f.Job, &f.Severity, &f.Title, &f.File, &f.Line, &f.Detail, &f.Status, &f.Created); err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	return out, rows.Err()
}

// ── notifications ──

// Notification is the standard cross-plugin notification record.
type Notification struct {
	ID       int64  `json:"id"`
	Type     string `json:"type"`
	Severity string `json:"severity"`
	Title    string `json:"title"`
	Body     string `json:"body"`
	Source   string `json:"source"`
	Dedupe   string `json:"dedupeKey,omitempty"`
	Created  string `json:"created"`
}

// AddNotification stores a notification; duplicate dedupe keys within 5
// minutes are dropped (returns id 0).
func (s *Store) AddNotification(n Notification) (int64, error) {
	if n.Dedupe != "" {
		cutoff := s.env.RT.Now().Add(-5 * time.Minute).Format(time.RFC3339)
		var count int
		_ = s.db.QueryRow(`SELECT COUNT(*) FROM plugin_notifications WHERE dedupe=? AND created>?`, n.Dedupe, cutoff).Scan(&count)
		if count > 0 {
			return 0, nil
		}
	}
	res, err := s.db.Exec(`INSERT INTO plugin_notifications (type, severity, title, body, source, dedupe, created)
		VALUES (?,?,?,?,?,?,?)`, n.Type, n.Severity, n.Title, n.Body, n.Source, n.Dedupe, s.now())
	if err != nil {
		return 0, err
	}
	return res.LastInsertId()
}

// Notifications returns the most recent limit rows.
func (s *Store) Notifications(limit int) ([]Notification, error) {
	rows, err := s.db.Query(`SELECT id, type, IFNULL(severity,''), title, IFNULL(body,''), IFNULL(source,''), IFNULL(dedupe,''), IFNULL(created,'')
		FROM plugin_notifications ORDER BY id DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []Notification
	for rows.Next() {
		var n Notification
		if err := rows.Scan(&n.ID, &n.Type, &n.Severity, &n.Title, &n.Body, &n.Source, &n.Dedupe, &n.Created); err != nil {
			return nil, err
		}
		out = append(out, n)
	}
	return out, rows.Err()
}

// ── plugin storage(插件私有 KV,读写都经 roam/storage.*)──

// StoragePath is the per-plugin KV file under the storage dir.
func (e Env) StoragePath(id string) string { return filepath.Join(e.StorageDir(id), "kv.json") }

// LoadStorage reads a plugin's private KV(文件不在 = 空表)。宿主侧只读:
// plugind 要据此判断「这个插件此刻有没有活要干」(如守护插件有没有守护对象),
// 而写入仍只发生在插件自己的 roam/storage.set 里。
func (e Env) LoadStorage(id string) map[string]string {
	kv := map[string]string{}
	if b, err := os.ReadFile(e.StoragePath(id)); err == nil {
		_ = json.Unmarshal(b, &kv)
	}
	return kv
}

// ── plugin config (schema 默认 < 全局配置;工作区覆盖为后续增量) ──

// ConfigPath is the per-plugin JSON config under the storage dir.
func (e Env) ConfigPath(id string) string { return filepath.Join(e.StorageDir(id), "config.json") }

// LoadConfig reads the plugin's config map (missing file = empty map).
func (e Env) LoadConfig(id string) (map[string]string, error) {
	cfg := map[string]string{}
	b, err := os.ReadFile(e.ConfigPath(id))
	if os.IsNotExist(err) {
		return cfg, nil
	}
	if err != nil {
		return nil, err
	}
	return cfg, json.Unmarshal(b, &cfg)
}

// SaveConfig persists the plugin's config map.
func (e Env) SaveConfig(id string, cfg map[string]string) error {
	if err := os.MkdirAll(e.StorageDir(id), 0o755); err != nil {
		return err
	}
	b, err := json.MarshalIndent(cfg, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(e.ConfigPath(id), b, 0o600)
}

func orDefault(v, def string) string {
	if v == "" {
		return def
	}
	return v
}
