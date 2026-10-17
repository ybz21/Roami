package metadb

import (
	"database/sql"
	"os"
	"testing"
	"time"
)

// TestAdoptRealHome 拿一份真实 Roami 主目录的**副本**跑一遍接管，
// 断言「只增不减」：老数据一行不少，新表都建出来，旧台账都收编了。
//
// 用 ROAM_TEST_HOME 指向副本目录才会跑（不设就跳过），绝不碰线上库。
func TestAdoptRealHome(t *testing.T) {
	dir := os.Getenv("ROAM_TEST_HOME")
	if dir == "" {
		t.Skip("设 ROAM_TEST_HOME=<真实主目录的副本> 才跑")
	}
	before := map[string]int{}
	for _, tb := range []string{"sessions", "swarms", "plugins", "plugin_sessions"} {
		before[tb] = rawCount(t, dir+"/meta.db", tb)
	}

	d, err := Open(dir, Options{DataDir: dir, HomeDir: dir, Now: time.Now})
	if err != nil {
		t.Fatal(err)
	}
	defer Discard(d.Path())

	// 1. 老数据一行不少
	for tb, want := range before {
		if want < 0 {
			continue // 老库本来就没这张表
		}
		var got int
		if err := d.QueryRow(`SELECT COUNT(*) FROM ` + tb).Scan(&got); err != nil {
			t.Fatalf("%s: %v", tb, err)
		}
		if got < want {
			t.Errorf("%s 迁移后 %d 行，少于迁移前 %d 行", tb, got, want)
		}
	}

	// 2. 新表建出来了，旧台账收编了
	v, _ := d.Version()
	t.Logf("schema 版本 = %d", v)
	for _, tb := range []string{"projects", "project_aliases", "races",
		"session_homes", "swarm_members", "swarm_cards", "tmux_epochs"} {
		var n int
		if err := d.QueryRow(`SELECT COUNT(*) FROM ` + tb).Scan(&n); err != nil {
			t.Errorf("%s: %v", tb, err)
			continue
		}
		t.Logf("  %-16s %d 行", tb, n)
	}
	t.Logf("收编结果：%s", LastReport())

	// 3. WAL 开起来了
	var journal string
	d.QueryRow(`PRAGMA journal_mode`).Scan(&journal)
	if journal != "wal" {
		t.Errorf("journal_mode = %q, want wal", journal)
	}

	// 4. 幂等：再开一次不重复导入
	projects := countLive(t, d, "projects")
	if err := Discard(d.Path()); err != nil {
		t.Fatal(err)
	}
	again, err := Open(dir, Options{DataDir: dir, HomeDir: dir, Now: time.Now})
	if err != nil {
		t.Fatal(err)
	}
	defer Discard(again.Path())
	if got := countLive(t, again, "projects"); got != projects {
		t.Errorf("再开一次后 projects = %d，之前是 %d（收编不幂等）", got, projects)
	}
}

// rawCount 直接开老库数行（还没接管，不能走 metadb）。表不存在返回 -1。
func rawCount(t *testing.T, path, table string) int {
	t.Helper()
	db, err := sql.Open("sqlite", "file:"+path+"?mode=ro")
	if err != nil {
		return -1
	}
	defer db.Close()
	var n int
	if db.QueryRow(`SELECT COUNT(*) FROM `+table).Scan(&n) != nil {
		return -1
	}
	return n
}

func countLive(t *testing.T, d *DB, table string) int {
	t.Helper()
	var n int
	d.QueryRow(`SELECT COUNT(*) FROM ` + table).Scan(&n)
	return n
}
