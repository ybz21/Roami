package metadb

import (
	"context"
	"database/sql"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"testing"

	"github.com/ybz21/Roami/backend/ttmux"
)

// schema 归 CLI 所有，而后端在 schema_testdata.go 里留了一份骨架副本——
// 两个 Go module 不能互相 import，只能各留一份。这条测试用**真 CLI** 建一次库，
// 逐列比对，把「两份定义悄悄漂开」变成一次失败的测试。
//
// 体例照 api/plugin_e2e_test.go：go build 真 CLI + 隔离 ROAM_HOME。
func TestSchemaMatchesRealCLI(t *testing.T) {
	if testing.Short() {
		t.Skip("要编译 CLI，-short 下跳过")
	}
	src := filepath.Join("..", "..")
	if _, err := os.Stat(src); err != nil {
		t.Skip("找不到 CLI 源码")
	}
	tmp := t.TempDir()
	bin := filepath.Join(tmp, "roami")
	build := exec.Command("go", "build", "-o", bin, "./cmd/roami")
	build.Dir = src
	if out, err := build.CombinedOutput(); err != nil {
		t.Skipf("编译 CLI 失败（环境问题，跳过）: %s", out)
	}

	home := filepath.Join(tmp, "roami-home")
	for _, prefix := range []string{"ROAMI", "ROAM", "TTMUX"} {
		for _, suffix := range []string{"HOME", "DATA", "CONFIG", "DATABASE_DIR", "BACKUP_DIR"} {
			t.Setenv(prefix+"_"+suffix, "")
		}
	}
	t.Setenv("ROAMI_HOME", home)
	t.Setenv("ROAMI_DATA", home)
	t.Setenv("ROAMI_DATABASE_DIR", filepath.Join(home, "database"))
	t.Setenv("ROAMI_BACKUP_DIR", filepath.Join(home, "backups"))
	t.Setenv("ROAMI_CONFIG", filepath.Join(home, "config.yaml"))
	real := exec.Command(bin, "session", "db", "migrate", "--json")
	real.Env = os.Environ()
	if out, err := real.CombinedOutput(); err != nil {
		t.Fatalf("roami db status 失败: %s", out)
	}

	d := Open(context.Background(), ttmux.New(bin), "")
	// Open 会自己再握手一次；这里只要拿到路径
	if !d.OK() {
		// 环境里没有 tmux 之类的原因不该让这条测试红——它只关心 schema
		t.Skipf("直连不上，跳过对拍: %s", d.Why())
	}
	defer d.Close()

	mine := filepath.Join(tmp, "mine.db")
	makeSchema(t, mine)
	mydb, err := sql.Open("sqlite", "file:"+mine)
	if err != nil {
		t.Fatal(err)
	}
	defer mydb.Close()

	for _, table := range []string{"projects", "project_aliases", "races", "session_homes", "sessions"} {
		want := columnsOf(t, d.SQL(), table) // 真 CLI 建的
		got := columnsOf(t, mydb, table)     // 后端这份骨架
		for _, c := range got {
			if !contains(want, c) {
				t.Errorf("%s: 后端骨架有列 %q，真 CLI 的库里没有——两份定义漂了", table, c)
			}
		}
		// 反向只警告：CLI 可以先加列，后端不认得也没关系（schema 只增不改）
		for _, c := range want {
			if !contains(got, c) {
				t.Logf("%s: CLI 新增了列 %q，后端骨架还没跟上（只增不改，暂时无害）", table, c)
			}
		}
	}
}

func columnsOf(t *testing.T, db *sql.DB, table string) []string {
	t.Helper()
	rows, err := db.Query(`PRAGMA table_info(` + table + `)`)
	if err != nil {
		t.Fatalf("%s: %v", table, err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var cid, notnull, pk int
		var name, typ string
		var dflt sql.NullString
		if rows.Scan(&cid, &name, &typ, &notnull, &dflt, &pk) == nil {
			out = append(out, name)
		}
	}
	sort.Strings(out)
	return out
}

func contains(xs []string, s string) bool {
	for _, x := range xs {
		if x == s {
			return true
		}
	}
	return false
}
