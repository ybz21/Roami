package metadb

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func testOpen(t *testing.T) *DB {
	t.Helper()
	dir := t.TempDir()
	d, err := Open(dir, Options{
		DataDir: dir,
		Now:     func() time.Time { return time.Date(2026, 8, 12, 19, 0, 0, 0, time.UTC) },
	})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = Discard(d.Path()) })
	return d
}

func TestFreshDBReachesLatestVersion(t *testing.T) {
	d := testOpen(t)
	v, err := d.Version()
	if err != nil {
		t.Fatal(err)
	}
	want := mainSteps[len(mainSteps)-1].Version
	if v != want {
		t.Fatalf("版本 = %d, want %d", v, want)
	}
	for _, tb := range []string{"sessions", "swarms", "plugins", "projects",
		"project_aliases", "races", "session_homes", "swarm_members", "swarm_cards",
		"tmux_epochs", "project_traces"} {
		if !HasTable(d.DB, tb) {
			t.Errorf("表 %s 没建出来", tb)
		}
	}
	cols, err := Columns(d.DB, "sessions")
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []string{"home_dir", "repo_root", "label", "status", "died_reason"} {
		if !cols[c] {
			t.Errorf("sessions 缺列 %s", c)
		}
	}
}

// 全新空库不该留下备份文件——不然每台新机器都多一个没用的 .bak。
func TestFreshDBLeavesNoBackup(t *testing.T) {
	d := testOpen(t)
	ents, _ := os.ReadDir(filepath.Dir(d.Path()))
	for _, e := range ents {
		if len(e.Name()) > 11 && e.Name()[:11] == "meta.db.bak" {
			t.Fatalf("全新库不该备份，却有 %s", e.Name())
		}
	}
}

func TestPragmasApplied(t *testing.T) {
	d := testOpen(t)
	var journal string
	if err := d.QueryRow(`PRAGMA journal_mode`).Scan(&journal); err != nil {
		t.Fatal(err)
	}
	if journal != "wal" {
		t.Fatalf("journal_mode = %q, want wal", journal)
	}
	var fk int
	if err := d.QueryRow(`PRAGMA foreign_keys`).Scan(&fk); err != nil {
		t.Fatal(err)
	}
	if fk != 1 {
		t.Fatal("foreign_keys 没开")
	}
	var busy int
	if err := d.QueryRow(`PRAGMA busy_timeout`).Scan(&busy); err != nil {
		t.Fatal(err)
	}
	if busy < 10000 {
		t.Fatalf("busy_timeout = %d, want >= 10000", busy)
	}
}

func TestOpenReturnsOneHandlePerPath(t *testing.T) {
	dir := t.TempDir()
	a, err := Open(dir, Options{DataDir: dir})
	if err != nil {
		t.Fatal(err)
	}
	defer Discard(a.Path())
	b, err := Open(dir, Options{DataDir: dir})
	if err != nil {
		t.Fatal(err)
	}
	if a != b {
		t.Fatal("同一个库应该复用同一个句柄（plugind 长驻 + 短操作要共池）")
	}
}

// Rows 没读完时连接是被占住的：池上限设成 1 会自锁。这条守住那个决定。
func TestQueryWhileRowsOpen(t *testing.T) {
	d := testOpen(t)
	for i := 0; i < 3; i++ {
		if _, err := d.Exec(`INSERT INTO sessions(id,created_at) VALUES(?,?)`,
			"s"+string(rune('a'+i)), "2026-08-12T19:00:00Z"); err != nil {
			t.Fatal(err)
		}
	}
	rows, err := d.Query(`SELECT id FROM sessions`)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	rows.Next() // 故意不读完

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var n int
	if err := d.QueryRowContext(ctx, `SELECT COUNT(*) FROM sessions`).Scan(&n); err != nil {
		t.Fatalf("Rows 未读完时再查应当能返回（池不能设成 1）: %v", err)
	}
	if n != 3 {
		t.Fatalf("COUNT = %d, want 3", n)
	}
}

func TestConcurrentWritesAllLand(t *testing.T) {
	d := testOpen(t)
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_, err := d.Exec(`INSERT INTO sessions(id,created_at) VALUES(?,?)`,
				"c"+string(rune('a'+i)), "2026-08-12T19:00:00Z")
			if err != nil {
				t.Errorf("并发写失败: %v", err)
			}
		}(i)
	}
	wg.Wait()
	var n int
	if err := d.QueryRow(`SELECT COUNT(*) FROM sessions`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 8 {
		t.Fatalf("写入 %d 行, want 8（SQLITE_BUSY 被吞掉了？）", n)
	}
}

func TestTxRollbackLeavesNothing(t *testing.T) {
	d := testOpen(t)
	wantErr := os.ErrInvalid
	err := d.Tx(func(tx *sql.Tx) error {
		if _, err := tx.Exec(`INSERT INTO sessions(id,created_at) VALUES('x','t')`); err != nil {
			return err
		}
		return wantErr
	})
	if err != wantErr {
		t.Fatalf("Tx 应把 fn 的错误原样返回, got %v", err)
	}
	var n int
	d.QueryRow(`SELECT COUNT(*) FROM sessions WHERE id='x'`).Scan(&n)
	if n != 0 {
		t.Fatal("回滚后不该留下行")
	}
}

// 把 bug 本身写成断言：开 WAL 之后，最近的提交还躺在 -wal 里没 checkpoint，
// 按字节拷贝会拷出一份少了几笔的库；VACUUM INTO 不会。
func TestBackupCapturesUncheckpointedWAL(t *testing.T) {
	d := testOpen(t)
	if _, err := d.Exec(`INSERT INTO sessions(id,created_at) VALUES('fresh','t')`); err != nil {
		t.Fatal(err)
	}

	// 对照组先做：VACUUM INTO 会顺带 checkpoint，先备份再拷就比不出差别了。
	raw := filepath.Join(t.TempDir(), "bytecopy.db")
	b, err := os.ReadFile(d.Path())
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(raw, b, 0o600); err != nil {
		t.Fatal(err)
	}
	byteCopyHas := countSession(t, raw, "fresh")

	bak, err := d.Backup("")
	if err != nil {
		t.Fatal(err)
	}
	if got := countSession(t, bak, "fresh"); got != 1 {
		t.Fatalf("VACUUM INTO 的备份里应当有这行, got %d", got)
	}
	// byteCopyHas: 0 = 表在但行不在；-1 = 连表都没有（schema 还全在 WAL 里）。
	// 两种都说明「按字节拷贝拿到的是残库」，正是这条测试要钉死的。
	if byteCopyHas == 1 {
		t.Skip("这台机器上 WAL 已提前 checkpoint，对照组不成立（VACUUM INTO 的正确性已在上面断言）")
	}
	t.Logf("对照组（按字节拷贝）读出 %d —— 残库，正是不能这么备份的原因", byteCopyHas)
}

func countSession(t *testing.T, path, id string) int {
	t.Helper()
	db, err := sql.Open("sqlite", "file:"+path+"?mode=ro")
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	var n int
	if err := db.QueryRow(`SELECT COUNT(*) FROM sessions WHERE id=?`, id).Scan(&n); err != nil {
		return -1
	}
	return n
}

func TestBackupRefusesToClobber(t *testing.T) {
	d := testOpen(t)
	dest := filepath.Join(t.TempDir(), "snap.db")
	first, err := d.Backup(dest)
	if err != nil {
		t.Fatal(err)
	}
	second, err := d.Backup(dest)
	if err != nil {
		t.Fatalf("同名备份应当加序号重试而不是报错: %v", err)
	}
	if first == second {
		t.Fatal("两次备份写到了同一个文件")
	}
}

// 父会话经常没有自己的行（只有 fork 出来的孩子才写行）。
// foreign_keys=ON 之下这条不变量必须还成立 —— 所以 parent_id 绝不能加 FK。
func TestParentWithoutRowStillInserts(t *testing.T) {
	d := testOpen(t)
	if _, err := d.Exec(`INSERT INTO sessions(id,parent_id,created_at) VALUES('kid','ghost-dad','t')`); err != nil {
		t.Fatalf("父无行时子会话必须插得进去: %v", err)
	}
}

// 表族内的 FK 该级联：删掉蜂群，成员和卡片跟着走。
func TestDeleteSwarmCascades(t *testing.T) {
	d := testOpen(t)
	if _, err := d.Exec(`INSERT INTO swarms(id,name) VALUES('s1','群')`); err != nil {
		t.Fatal(err)
	}
	if _, err := d.Exec(`INSERT INTO swarm_members(swarm_id,name) VALUES('s1','m1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := d.Exec(`INSERT INTO swarm_cards(swarm_id,id) VALUES('s1','c1')`); err != nil {
		t.Fatal(err)
	}
	if _, err := d.Exec(`DELETE FROM swarms WHERE id='s1'`); err != nil {
		t.Fatal(err)
	}
	for _, tb := range []string{"swarm_members", "swarm_cards"} {
		var n int
		d.QueryRow(`SELECT COUNT(*) FROM ` + tb).Scan(&n)
		if n != 0 {
			t.Errorf("%s 没跟着级联删除", tb)
		}
	}
}

// 老 plugind 还活着、CLI 已经升级过 —— 版本比我新时不能报错。
func TestNewerDBVersionIsTolerated(t *testing.T) {
	d := testOpen(t)
	if _, err := d.Exec(`INSERT INTO schema_meta(version,name,applied_at) VALUES(99,'future','t')`); err != nil {
		t.Fatal(err)
	}
	path := d.Path()
	if err := Discard(path); err != nil {
		t.Fatal(err)
	}
	again, err := OpenFile(path, mainSteps, Options{})
	if err != nil {
		t.Fatalf("版本比本二进制新时不该报错: %v", err)
	}
	defer Discard(again.Path())
}

// activity.log 收编：两代都要收，坏行只丢自己，重跑不翻倍。
func TestImportsActivityLog(t *testing.T) {
	dir := t.TempDir()
	write := func(name string, lines ...string) {
		if err := os.WriteFile(filepath.Join(dir, name),
			[]byte(strings.Join(lines, "\n")+"\n"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	write("activity.log.1", `{"id":"t-old","repo":"/repo/a","branch":"ancient","action":"merged","at":100}`)
	write("activity.log",
		`{"id":"t-new","repo":"/repo/a","branch":"fresh","action":"discarded","at":200,"mergedInto":"main","mergedKind":"squash"}`,
		`{"repo":"/repo/b","branch":"noid","action":"cleaned","at":150}`, // 老行没有 id
		`{"repo":"/repo/b","branch":"半`, // 坏行：只丢它一条
	)

	d, err := Open(dir, Options{DataDir: dir, Now: func() time.Time { return time.Unix(0, 0) }})
	if err != nil {
		t.Fatal(err)
	}
	defer Discard(d.Path())

	var n int
	if err := d.QueryRow(`SELECT COUNT(*) FROM project_traces`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 3 {
		t.Fatalf("应当收 3 条（坏行丢掉）, got %d", n)
	}
	var branch, into, kind string
	if err := d.QueryRow(`SELECT branch, IFNULL(merged_into,''), IFNULL(merged_kind,'')
		FROM project_traces WHERE id='t-new'`).Scan(&branch, &into, &kind); err != nil {
		t.Fatal(err)
	}
	if branch != "fresh" || into != "main" || kind != "squash" {
		t.Fatalf("字段没搬全: %s %s %s", branch, into, kind)
	}
	// 没有 id 的老行按内容派了一个稳定 id
	var noid string
	if err := d.QueryRow(`SELECT id FROM project_traces WHERE branch='noid'`).Scan(&noid); err != nil {
		t.Fatal(err)
	}
	if noid == "" {
		t.Fatal("老行应当派到 id")
	}

	// 再跑一遍收编（模拟「导到一半崩了」重来）：不该翻倍
	if err := importTraces2(d, dir); err != nil {
		t.Fatal(err)
	}
	var again int
	if err := d.QueryRow(`SELECT COUNT(*) FROM project_traces`).Scan(&again); err != nil {
		t.Fatal(err)
	}
	if again != n {
		t.Fatalf("重跑翻倍了: %d → %d", n, again)
	}
}

// importTraces2 手动再跑一次收编（版本链已盖章，正常路径不会再跑）。
func importTraces2(d *DB, dataDir string) error {
	return d.Tx(func(tx *sql.Tx) error { return importTraces(tx, Options{DataDir: dataDir}) })
}
