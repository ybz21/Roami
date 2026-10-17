package metadb

// TestSchema 是一份**够测试用**的表骨架。
//
// schema 的真相源是 ttmux CLI 的 internal/metadb —— 两个 Go module 不能互相 import
// （见 backend/internal/id 的包注释），所以只能各留一份。生产代码一行 DDL 都不跑，
// 这份常量只被测试引用；真结构漂了靠 TestSchemaMatchesRealCLI 用真 CLI 对拍抓出来。
// 导出是为了让别的包（project 等）在测试里摆**同一份**骨架：多摆一份就是第三个会漂开的定义。
const TestSchema = `
CREATE TABLE IF NOT EXISTS projects(
	id TEXT PRIMARY KEY, dir TEXT NOT NULL UNIQUE, origin TEXT NOT NULL DEFAULT '',
	display_name TEXT, pinned INTEGER NOT NULL DEFAULT 0,
	default_agent TEXT, default_base TEXT,
	first_seen INTEGER NOT NULL DEFAULT 0, last_seen INTEGER NOT NULL DEFAULT 0,
	last_session_at INTEGER NOT NULL DEFAULT 0, archived_at INTEGER);
CREATE TABLE IF NOT EXISTS project_aliases(
	alias TEXT PRIMARY KEY,
	project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS races(
	id TEXT PRIMARY KEY, legacy_id TEXT, name TEXT, dir TEXT NOT NULL DEFAULT '',
	base TEXT, prompt TEXT, created_at TEXT, status TEXT NOT NULL DEFAULT 'running',
	winner TEXT, crown_done TEXT, contestants TEXT);
CREATE TABLE IF NOT EXISTS session_homes(
	tmux_id TEXT PRIMARY KEY, epoch TEXT, name TEXT, home TEXT NOT NULL,
	pinned_at INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS project_traces(
	id TEXT PRIMARY KEY, repo TEXT NOT NULL DEFAULT '', branch TEXT, head_oid TEXT,
	base TEXT, action TEXT, strategy TEXT, at INTEGER NOT NULL DEFAULT 0,
	merged_into TEXT, merged_kind TEXT);
CREATE INDEX IF NOT EXISTS project_traces_repo ON project_traces(repo, at DESC);
CREATE TABLE IF NOT EXISTS sessions(
	id TEXT PRIMARY KEY, parent_id TEXT, created_by TEXT, created_at TEXT,
	initial_cwd TEXT, status TEXT NOT NULL DEFAULT 'live', died_at TEXT,
	died_reason TEXT, tmux_id TEXT, tmux_epoch TEXT,
	home_dir TEXT, repo_root TEXT, label TEXT);
`
