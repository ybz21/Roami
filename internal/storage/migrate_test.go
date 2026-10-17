package metadb

import (
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

var fixedNow = func() time.Time { return time.Date(2026, 7, 28, 11, 13, 0, 0, time.UTC) }

// adopt 打开一个已经摆好老数据的目录，返回接管后的库。
func adopt(t *testing.T, dir string) *DB {
	t.Helper()
	p, err := ResolvePaths(dir, dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = p.ReadLayout(); err != nil {
		if err = p.MigrateLayout(true); err != nil {
			t.Fatal(err)
		}
	}
	d, err := Open(dir, Options{DataDir: dir, Now: fixedNow})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = Discard(d.Path()) })
	return d
}

func sessionRow(t *testing.T, d *DB, id string) (parent, by, at, cwd, status string, ok bool) {
	t.Helper()
	err := d.QueryRow(`SELECT IFNULL(parent_id,''), IFNULL(created_by,''), IFNULL(created_at,''),
		IFNULL(initial_cwd,''), status FROM sessions WHERE id=?`, id).
		Scan(&parent, &by, &at, &cwd, &status)
	return parent, by, at, cwd, status, err == nil
}

// v1 老库（会话名当主键）：主键正好就是现在要的持久 id，直接搬，一行不丢。
// 关键是**不问 tmux** —— 老实现要先拿到「名字 → $N」才肯搬，tmux 一死就整批丢弃，
// 那正是重启后会话历史被清空的第二重原因。
func TestAdoptV1Sessions(t *testing.T) {
	dir := t.TempDir()
	writeV1(t, filepath.Join(dir, "meta.db"), []v1row{
		{"kid", "dad", "fork", "2026-07-01T00:00:00Z", "/repo"},
		{"dad", "", "new", "2026-07-01T00:00:00Z", ""},
		{"ghost", "", "fork", "2026-06-01T00:00:00Z", "/gone"},
	})
	d := adopt(t, dir)

	parent, by, at, cwd, status, ok := sessionRow(t, d, "kid")
	if !ok {
		t.Fatal("kid 没搬过来")
	}
	if parent != "dad" || by != "fork" || at != "2026-07-01T00:00:00Z" || cwd != "/repo" {
		t.Fatalf("迁移丢字段: parent=%q by=%q at=%q cwd=%q", parent, by, at, cwd)
	}
	if status != "live" {
		t.Fatalf("不问 tmux 时应先当 live（Reconcile 之后自愈），got %q", status)
	}
	// 会话早没了的行也要留着——只增不减
	if _, _, _, cwd, _, ok := sessionRow(t, d, "ghost"); !ok || cwd != "/gone" {
		t.Fatal("ghost 应当保留，且带着它的起始目录")
	}
	if HasTable(d.DB, "sessions_v1") {
		t.Fatal("迁移成功后应删掉 sessions_v1")
	}
}

// v2 老库（$N 当主键、名字在 name 列）：按 name 重建主键，parent 的 $N 用
// **同表内**的映射翻译。同样不依赖 tmux。
func TestAdoptV2Sessions(t *testing.T) {
	dir := t.TempDir()
	writeV2(t, filepath.Join(dir, "meta.db"), []v2row{
		{"$2", "kid", "$1", "fork", "2026-07-01T00:00:00Z", "/repo"},
		{"$1", "dad", "", "new", "2026-07-01T00:00:00Z", "/repo"},
	})
	d := adopt(t, dir)

	parent, by, _, cwd, _, ok := sessionRow(t, d, "kid")
	if !ok {
		t.Fatal("kid 没搬过来")
	}
	if parent != "dad" {
		t.Fatalf("parent 的 $N 没被翻译成会话名，got %q", parent)
	}
	if by != "fork" || cwd != "/repo" {
		t.Fatalf("v2 迁移丢字段: by=%q cwd=%q", by, cwd)
	}
	if HasTable(d.DB, "sessions_v2") {
		t.Fatal("迁移成功后应删掉 sessions_v2")
	}
}

// 接管老库要留一份后悔药；全新空库不留（TestFreshDBLeavesNoBackup 管另一半）。
func TestAdoptBacksUpOldDB(t *testing.T) {
	dir := t.TempDir()
	writeV1(t, filepath.Join(dir, "meta.db"), []v1row{{"kid", "", "new", "t", ""}})
	adopt(t, dir)

	ents, _ := os.ReadDir(filepath.Join(dir, "backups"))
	n := 0
	for _, e := range ents {
		if strings.HasPrefix(e.Name(), "pre-layout-") {
			n++
		}
	}
	if n != 1 {
		t.Fatalf("接管老库应当备份恰好一份，got %d", n)
	}
}

// 老 swarms 表没有 dir 列 —— baseline 要补上而不是报错。
func TestAdoptSwarmsWithoutDirColumn(t *testing.T) {
	dir := t.TempDir()
	raw := openRaw(t, filepath.Join(dir, "meta.db"))
	mustExec(t, raw, `CREATE TABLE swarms(id TEXT PRIMARY KEY, name TEXT UNIQUE, goal TEXT,
		status TEXT, supervisor TEXT, created TEXT)`)
	mustExec(t, raw, `INSERT INTO swarms(id,name) VALUES('s1','群')`)
	raw.Close()

	d := adopt(t, dir)
	cols, err := Columns(d.DB, "swarms")
	if err != nil {
		t.Fatal(err)
	}
	if !cols["dir"] {
		t.Fatal("dir 列没补上")
	}
	var n int
	d.QueryRow(`SELECT COUNT(*) FROM swarms`).Scan(&n)
	if n != 1 {
		t.Fatal("老行丢了")
	}
}

// 老 plugins 表没有 install_path / removed —— 同样要补。
func TestAdoptPluginTablesWithoutNewColumns(t *testing.T) {
	dir := t.TempDir()
	raw := openRaw(t, filepath.Join(dir, "meta.db"))
	mustExec(t, raw, `CREATE TABLE plugins (id TEXT PRIMARY KEY, version TEXT, kind TEXT,
		enabled INTEGER DEFAULT 0, manifest TEXT, installed TEXT)`)
	mustExec(t, raw, `INSERT INTO plugins(id) VALUES('p1')`)
	raw.Close()

	d := adopt(t, dir)
	cols, err := Columns(d.DB, "plugins")
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []string{"install_path", "removed"} {
		if !cols[c] {
			t.Errorf("plugins 缺列 %s", c)
		}
	}
}

// 两个独立连接同时迁移（对 SQLite 就是两个进程）：都不该报错，且只盖一次章。
// 这条顶掉了原先 sessmeta 里那段「ALTER 失败就重新探测版本」的特判兜底。
func TestConcurrentMigrateStampsOnce(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "meta.db")
	errs := make(chan error, 2)
	for i := 0; i < 2; i++ {
		go func() {
			db, err := openWithFallback(path)
			if err != nil {
				errs <- err
				return
			}
			defer db.Close()
			errs <- migrate(&DB{DB: db, path: path}, mainSteps, Options{DataDir: dir, Now: fixedNow})
		}()
	}
	for i := 0; i < 2; i++ {
		if err := <-errs; err != nil {
			t.Fatalf("并发迁移不该报错: %v", err)
		}
	}
	d := adopt(t, dir)
	var dup int
	d.QueryRow(`SELECT COUNT(*) - COUNT(DISTINCT version) FROM schema_meta`).Scan(&dup)
	if dup != 0 {
		t.Fatal("schema_meta 出现重复版本行")
	}
}

// ── 造老库的辅助 ────────────────────────────────────────────────────────

type v1row struct{ session, parent, by, at, cwd string }
type v2row struct{ id, name, parentID, by, at, cwd string }

func openRaw(t *testing.T, path string) *sql.DB {
	t.Helper()
	db, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatal(err)
	}
	return db
}

func mustExec(t *testing.T, db *sql.DB, q string, args ...any) {
	t.Helper()
	if _, err := db.Exec(q, args...); err != nil {
		t.Fatal(err)
	}
}

func writeV1(t *testing.T, path string, rows []v1row) {
	t.Helper()
	db := openRaw(t, path)
	defer db.Close()
	mustExec(t, db, `CREATE TABLE sessions(
		session TEXT PRIMARY KEY, parent TEXT, created_by TEXT, created_at TEXT, initial_cwd TEXT)`)
	for _, r := range rows {
		mustExec(t, db, `INSERT INTO sessions VALUES(?,NULLIF(?,''),?,?,?)`,
			r.session, r.parent, r.by, r.at, r.cwd)
	}
}

func writeV2(t *testing.T, path string, rows []v2row) {
	t.Helper()
	db := openRaw(t, path)
	defer db.Close()
	mustExec(t, db, `CREATE TABLE sessions(
		id TEXT PRIMARY KEY, name TEXT, parent_id TEXT, created_by TEXT, created_at TEXT, initial_cwd TEXT)`)
	for _, r := range rows {
		mustExec(t, db, `INSERT INTO sessions VALUES(?,?,NULLIF(?,''),?,?,?)`,
			r.id, r.name, r.parentID, r.by, r.at, r.cwd)
	}
}

// 被推迟的步骤**不能挡住后面的步骤**。
//
// 收编那一步在缺 DataDir 时会推迟（plugind 之类的入口开库时给不全）。如果驱动
// 按 MAX(version) 判「做到哪了」，这一推迟就会把它后面所有步骤永远关在门外——
// 实际踩到过：sessions 少了一列，History() 整条 SELECT 失败、历史读出来是空的。
func TestDeferredStepDoesNotBlockLaterOnes(t *testing.T) {
	dir := t.TempDir()
	// 不给 DataDir → 收编那一步推迟
	d, err := Open(dir, Options{Now: fixedNow})
	if err != nil {
		t.Fatal(err)
	}
	defer Discard(d.Path())

	done, err := appliedSteps(d.DB)
	if err != nil {
		t.Fatal(err)
	}
	// 收编类的步骤都吃 DataDir，缺它就该推迟；**其余每一步都必须照常应用**——
	// 尤其是排在推迟那步后面的。
	needsDataDir := map[string]bool{"import-legacy": true, "import-traces": true}
	for _, st := range mainSteps {
		if !needsDataDir[st.Name] && !done[st.Version] {
			t.Fatalf("v%d(%s) 应当照常应用，实际已应用 %v", st.Version, st.Name, done)
		}
	}
	// 推迟的那步确实没盖章，留着下次补
	var deferred int
	for _, st := range mainSteps {
		if st.Name == "import-legacy" {
			deferred = st.Version
		}
	}
	if done[deferred] {
		t.Fatal("缺 DataDir 时收编不该盖章")
	}
	// sessions 的列必须齐 —— History() 依赖它们
	cols, err := Columns(d.DB, "sessions")
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []string{"home_dir", "repo_root", "label", "agent_session_uuid"} {
		if !cols[c] {
			t.Errorf("sessions 缺列 %s（被推迟的步骤挡住了？）", c)
		}
	}

	// 下次带上 DataDir → 补做
	if err := Discard(d.Path()); err != nil {
		t.Fatal(err)
	}
	again, err := Open(dir, Options{DataDir: dir, Now: fixedNow})
	if err != nil {
		t.Fatal(err)
	}
	defer Discard(again.Path())
	done2, _ := appliedSteps(again.DB)
	if !done2[deferred] {
		t.Fatal("带上 DataDir 后应当把推迟的那步补上")
	}
}
