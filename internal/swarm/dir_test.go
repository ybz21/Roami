package swarm

import (
	"database/sql"
	metadb "github.com/ybz21/Roami/internal/storage"
	"os"
	"path/filepath"
	"testing"
	"time"

	_ "modernc.org/sqlite"
)

func testOpts(t *testing.T) Options {
	t.Helper()
	home := filepath.Join(t.TempDir(), "h")
	return Options{HomeDir: home, DataDir: filepath.Join(home, "data"), Now: func() time.Time { return time.Unix(100, 0) }}
}

// 建群时记下的工作目录要能从 swarm ls / swarm status 两条路读回来——
// Web 项目视图就是靠它归属蜂群的(issue #125)。
func TestSwarmDirRoundTrip(t *testing.T) {
	opt := testOpts(t)
	st := NewStore(opt)
	if _, err := st.NewSwarm("sw", "goal", "/tmp/proj-a"); err != nil {
		t.Fatal(err)
	}
	rows, err := st.ListSwarms()
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 || rows[0].Dir != "/tmp/proj-a" {
		t.Fatalf("ListSwarms dir=%+v want /tmp/proj-a", rows)
	}
	stt, err := Status("sw", opt)
	if err != nil {
		t.Fatal(err)
	}
	if stt.Dir != "/tmp/proj-a" {
		t.Errorf("Status dir=%q want /tmp/proj-a", stt.Dir)
	}
	// adopt --dir 走 MetaSet 改目录
	if err := st.MetaSet("sw", "dir", "/tmp/proj-b"); err != nil {
		t.Fatal(err)
	}
	if got := st.MetaGet("sw", "dir"); got != "/tmp/proj-b" {
		t.Errorf("MetaGet dir=%q want /tmp/proj-b", got)
	}
}

// 老库(没有 dir 列)打开时应就地补列，且补两次不报错。
func TestMetaDirMigrationIdempotent(t *testing.T) {
	opt := testOpts(t)
	if err := os.MkdirAll(opt.HomeDir, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(opt.HomeDir, "meta.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TABLE swarms(id TEXT PRIMARY KEY, name TEXT UNIQUE, goal TEXT, status TEXT, supervisor TEXT, created TEXT);
		INSERT INTO swarms(id,name,goal,status,supervisor,created) VALUES('sw1','old','g','running','','2026-06-22 10:00:00');`); err != nil {
		t.Fatal(err)
	}
	db.Close()

	paths, e := metadb.ResolvePaths(opt.HomeDir, opt.DataDir)
	if e != nil {
		t.Fatal(e)
	}
	if e = paths.MigrateLayout(true); e != nil {
		t.Fatal(e)
	}
	st := NewStore(opt)
	for i := 0; i < 2; i++ {
		if err := st.MetaInit(); err != nil {
			t.Fatalf("MetaInit #%d: %v", i+1, err)
		}
	}
	rows, err := st.ListSwarms()
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 || rows[0].Name != "old" || rows[0].Dir != "" {
		t.Fatalf("ListSwarms=%+v want one row 'old' with empty dir", rows)
	}
	if err := st.MetaSet("old", "dir", "/tmp/legacy"); err != nil {
		t.Fatal(err)
	}
	if got := st.MetaGet("old", "dir"); got != "/tmp/legacy" {
		t.Errorf("MetaGet dir=%q want /tmp/legacy", got)
	}
}
