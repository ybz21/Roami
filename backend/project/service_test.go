package project

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	_ "modernc.org/sqlite"

	"github.com/ybz21/Roami/backend/ttmux"
	"github.com/ybz21/Roami/internal/id"
	"github.com/ybz21/Roami/internal/metadb"
)

func TestStorePersistAndConverge(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(dir, nil)
	key := s.Touch("/tmp/demo-repo")
	if !id.Valid(key) {
		t.Fatalf("Touch 应发不可变 id，got %q", key)
	}
	if _, ok := s.Dir(key); !ok {
		t.Fatal("Touch 后应在册")
	}
	if key2 := s.Touch("/tmp/demo-repo"); key2 != key {
		t.Fatalf("同目录重复 Touch 必须复用同一 id: %q vs %q", key, key2)
	}
	if !s.SetPrefs(key, func(p *Prefs) { p.Pinned = true }) {
		t.Fatal("SetPrefs 在册 key 应成功")
	}
	// 重新加载：台账与偏好都持久化
	s2 := NewStore(dir, nil)
	e := s2.Entries()[key]
	if e.Dir != "/tmp/demo-repo" || !e.Pinned || e.ID != key {
		t.Fatalf("重载后丢数据: %+v", e)
	}
	s2.Remove(key)
	if _, ok := s2.Dir(key); ok {
		t.Fatal("Remove 后不应在册")
	}
	// 落盘的是原子替换后的完整文件
	if _, err := os.Stat(filepath.Join(dir, "projects.json")); err != nil {
		t.Fatal("projects.json 应存在")
	}
	if s3 := NewStore(dir, nil); len(s3.Entries()) != 0 {
		t.Fatal("Remove 也要持久化")
	}
}

func TestSetPrefsUnknownKey(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	if s.SetPrefs("nope-0000", func(p *Prefs) { p.Pinned = true }) {
		t.Fatal("不在册 key 必须拒绝（API 防任意路径探测的前提）")
	}
}

// 目录搬家（mv 项目 / worktree 子目录归位仓库根）：id 不变、偏好不丢。
func TestSetDirKeepsIdentity(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	k, _ := s.Add("/repo/old", "我的项目")
	s.SetPrefs(k, func(p *Prefs) { p.Pinned = true })
	if got := s.SetDir(k, "/repo/new"); got != k {
		t.Fatalf("平移应保持 id: %q → %q", k, got)
	}
	e := s.Entries()[k]
	if e.Dir != "/repo/new" || !e.Pinned || e.DisplayName != "我的项目" {
		t.Fatalf("搬家后偏好丢了: %+v", e)
	}
	if k2 := s.Touch("/repo/new"); k2 != k { // byDir 索引跟着搬
		t.Fatalf("新目录应命中同一条目: %q vs %q", k, k2)
	}
	if _, ok := s.byDir["/repo/old"]; ok {
		t.Fatal("老目录索引应清掉")
	}
}

// 新目录已被别的条目占用 → 合并用户意志，被并掉的 id 变别名（老链接仍可解析）。
func TestSetDirMergesUserIntent(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	sub, _ := s.Add("/repo/.worktrees", "")
	s.SetPrefs(sub, func(p *Prefs) { p.Pinned = true })
	root := s.Touch("/repo")
	if got := s.SetDir(sub, "/repo"); got != root {
		t.Fatalf("应并进根条目 %q，got %q", root, got)
	}
	e := s.Entries()[root]
	if !e.Pinned || e.Origin != "user" {
		t.Fatalf("合并须保留用户意志(置顶/origin=user): %+v", e)
	}
	if len(s.Entries()) != 1 {
		t.Fatalf("合并后应只剩一条: %+v", s.Entries())
	}
	if d, ok := s.Dir(sub); !ok || d != "/repo" { // 被合并的老 id 仍解析得到
		t.Fatalf("被合并的 id 应作为别名继续解析，got %q ok=%v", d, ok)
	}
}

// v1 文件（key = 目录名 slug + 路径 hash）迁移：发 id、老 key 留别名、偏好原样。
func TestLegacyKeyMigration(t *testing.T) {
	dir := t.TempDir()
	legacy := `{"repos":{"ttmux-3f2a":{"dir":"/home/u/codes/ttmux","origin":"user","pinned":true,"displayName":"Roami","firstSeen":100,"lastSeen":200}}}`
	if err := os.WriteFile(filepath.Join(dir, "projects.json"), []byte(legacy), 0o600); err != nil {
		t.Fatal(err)
	}
	s := NewStore(dir, nil)
	ents := s.Entries()
	if len(ents) != 1 {
		t.Fatalf("迁移后应有 1 条: %+v", ents)
	}
	var newKey string
	for k := range ents {
		newKey = k
	}
	if !id.Valid(newKey) {
		t.Fatalf("迁移后 key 应是 id，got %q", newKey)
	}
	e := ents[newKey]
	if e.ID != newKey || e.Dir != "/home/u/codes/ttmux" || !e.Pinned || e.DisplayName != "Roami" || e.Origin != "user" || e.FirstSeen != 100 {
		t.Fatalf("迁移丢字段: %+v", e)
	}
	// 老书签 #/projects/ttmux-3f2a 仍能解析
	if d, ok := s.Dir("ttmux-3f2a"); !ok || d != "/home/u/codes/ttmux" {
		t.Fatalf("老 key 别名失效: %q ok=%v", d, ok)
	}
	if !s.SetPrefs("ttmux-3f2a", func(p *Prefs) { p.DefaultBase = "main" }) {
		t.Fatal("老 key 也应能改偏好")
	}
	// 迁移结果落盘：重开仍是 id 主键 + 别名可用
	s2 := NewStore(dir, nil)
	if _, ok := s2.Entries()[newKey]; !ok {
		t.Fatal("迁移未落盘")
	}
	if _, ok := s2.Dir("ttmux-3f2a"); !ok {
		t.Fatal("别名未落盘")
	}
	var f fileShape
	b, _ := os.ReadFile(filepath.Join(dir, "projects.json"))
	if json.Unmarshal(b, &f) != nil || f.Aliases["ttmux-3f2a"] != newKey {
		t.Fatalf("落盘文件缺 aliases: %s", b)
	}
	// 删除后别名一并清掉，不留悬空
	s2.Remove(newKey)
	if _, ok := s2.Dir("ttmux-3f2a"); ok {
		t.Fatal("条目删了别名还在")
	}
}

// 历史脏数据：两条条目指向同一目录 → 加载时合并成一条。
func TestLoadMergesDuplicateDirs(t *testing.T) {
	dir := t.TempDir()
	legacy := `{"repos":{
		"a-0001":{"dir":"/x","pinned":true,"firstSeen":50},
		"a-0002":{"dir":"/x","origin":"user","displayName":"X","firstSeen":10}}}`
	if err := os.WriteFile(filepath.Join(dir, "projects.json"), []byte(legacy), 0o600); err != nil {
		t.Fatal(err)
	}
	s := NewStore(dir, nil)
	if len(s.Entries()) != 1 {
		t.Fatalf("同目录重复条目应合并: %+v", s.Entries())
	}
	for _, e := range s.Entries() {
		if !e.Pinned || e.Origin != "user" || e.DisplayName != "X" || e.FirstSeen != 10 {
			t.Fatalf("合并丢用户意志: %+v", e)
		}
	}
	for _, k := range []string{"a-0001", "a-0002"} {
		if d, ok := s.Dir(k); !ok || d != "/x" {
			t.Fatalf("老 key %s 应仍解析到 /x", k)
		}
	}
}

// 留痕从文件尾部回读：要的永远是最新那几条，而文件会长到 5MB 才轮转。
// 这几条同时钉住「新在前」「按仓库过滤」「跨块边界不丢行」「够了就不再往回读」。
func TestReadTraceReturnsNewestFirst(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(dir, nil)
	for i := 0; i < 5; i++ {
		s.Trace(TraceEntry{Repo: "/repo/a", Branch: fmt.Sprintf("b%d", i), Action: "merged"})
		s.Trace(TraceEntry{Repo: "/repo/other", Branch: "noise", Action: "cleaned"})
	}
	got := s.ReadTrace("/repo/a", 3)
	if len(got) != 3 {
		t.Fatalf("要 3 条, got %d", len(got))
	}
	for i, want := range []string{"b4", "b3", "b2"} {
		if got[i].Branch != want {
			t.Fatalf("第 %d 条 = %q, want %q（新在前）", i, got[i].Branch, want)
		}
	}
	for _, e := range got {
		if e.Repo != "/repo/a" {
			t.Fatalf("串了别的仓库: %+v", e)
		}
	}
}

// 单条留痕远小于块大小，但总量要能跨过 64KB 的块边界——回读时那里最容易丢行。
func TestReadTraceAcrossChunkBoundary(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(dir, nil)
	// 每条塞一段长 branch 名，几百条就能跨过 64KB
	pad := strings.Repeat("x", 300)
	const n = 400
	for i := 0; i < n; i++ {
		s.Trace(TraceEntry{Repo: "/repo/a", Branch: fmt.Sprintf("%s-%d", pad, i), Action: "merged"})
	}
	got := s.ReadTrace("/repo/a", n)
	if len(got) != n {
		t.Fatalf("跨块回读丢了行: got %d, want %d", len(got), n)
	}
	if !strings.HasSuffix(got[0].Branch, fmt.Sprintf("-%d", n-1)) {
		t.Fatalf("最新那条不对: %q", got[0].Branch)
	}
	if !strings.HasSuffix(got[n-1].Branch, "-0") {
		t.Fatalf("最老那条不对: %q", got[n-1].Branch)
	}
}

// 轮转过一代之后，当前这代不够就该往上一代找。
func TestReadTraceFallsBackToRotated(t *testing.T) {
	dir := t.TempDir()
	s := NewStore(dir, nil)
	old := filepath.Join(dir, "activity.log.1")
	line, _ := json.Marshal(TraceEntry{Repo: "/repo/a", Branch: "ancient", Action: "merged"})
	if err := os.WriteFile(old, append(line, '\n'), 0o600); err != nil {
		t.Fatal(err)
	}
	s.Trace(TraceEntry{Repo: "/repo/a", Branch: "fresh", Action: "merged"})

	got := s.ReadTrace("/repo/a", 10)
	if len(got) != 2 || got[0].Branch != "fresh" || got[1].Branch != "ancient" {
		t.Fatalf("轮转两代应当都读到且新在前: %+v", got)
	}
	// 当前这代就够了的话，不必去翻上一代
	if one := s.ReadTrace("/repo/a", 1); len(one) != 1 || one[0].Branch != "fresh" {
		t.Fatalf("limit=1 应当只给最新那条: %+v", one)
	}
}

// ── 直连模式下的留痕 ─────────────────────────────────────────────────────

// dbStore 造一个直连模式的 Store：真 sqlite 文件 + 真握手路径（假 CLI 只负责报路径）。
// 走 metadb.Open 而不是自己拼一个 DB，是为了让「库路径只能来自握手」那条约束在这里也成立。
func dbStore(t *testing.T) *Store {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "meta.db")
	raw, err := sql.Open("sqlite", "file:"+path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := raw.Exec(metadb.TestSchema); err != nil {
		t.Fatal(err)
	}
	raw.Close()

	bin := filepath.Join(dir, "ttmux")
	script := "#!/bin/sh\nif [ \"$1\" = db ]; then printf '%s' '" +
		`{"path":"` + path + `","schemaVersion":6,"minCompatible":1,"journalMode":"wal"}` + "'; fi\n"
	if err := os.WriteFile(bin, []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	db := metadb.Open(context.Background(), ttmux.New(bin), "")
	if !db.OK() {
		t.Fatalf("应当直连成功: %s", db.Why())
	}
	t.Cleanup(func() { db.Close() })
	return NewStore(dir, db)
}

// 直连模式下留痕必须真的落库。
//
// 这是一条**回归**测试：并库之后 Store 在直连模式下不再有文件路径（path 只在降级
// 分支赋值），而 Trace/ReadTrace 当时还只认文件——于是每一条留痕都被静默丢掉、
// 项目活动恒空，还不报错。
func TestTraceGoesToDBWhenConnected(t *testing.T) {
	s := dbStore(t)
	if s.tracePath() != "" {
		t.Fatal("直连模式不该再有留痕文件路径")
	}
	s.Trace(TraceEntry{Repo: "/repo/a", Branch: "b1", Action: "merged"})
	s.Trace(TraceEntry{Repo: "/repo/other", Branch: "noise", Action: "cleaned"})
	s.Trace(TraceEntry{Repo: "/repo/a", Branch: "b2", Action: "discarded", MergedInto: "main", MergedKind: "squash"})

	got := s.ReadTrace("/repo/a", 10)
	if len(got) != 2 {
		t.Fatalf("要 2 条（本仓库的）, got %d: %+v", len(got), got)
	}
	if got[0].Branch != "b2" || got[1].Branch != "b1" {
		t.Fatalf("应当新在前: %+v", got)
	}
	if got[0].MergedInto != "main" || got[0].MergedKind != "squash" || got[0].Action != "discarded" {
		t.Fatalf("字段丢了: %+v", got[0])
	}
	if got[0].At == 0 || got[0].ID == "" {
		t.Fatalf("时间/id 应当写入时补上: %+v", got[0])
	}
}

// 同一秒里连着落的几条（一次清理会一口气写好几条）光看 at 分不出先后，
// 得靠 rowid 兜底定序，否则活动列表的顺序会随查询计划漂。
func TestTraceOrdersWithinSameSecond(t *testing.T) {
	s := dbStore(t)
	for i := 0; i < 5; i++ {
		s.Trace(TraceEntry{Repo: "/repo/a", Branch: fmt.Sprintf("b%d", i), Action: "cleaned"})
	}
	got := s.ReadTrace("/repo/a", 3)
	for i, want := range []string{"b4", "b3", "b2"} {
		if got[i].Branch != want {
			t.Fatalf("第 %d 条 = %q, want %q", i, got[i].Branch, want)
		}
	}
}

// 文件形态靠 5MB 轮转给读放大封顶；进了库要自己修剪，否则只增不减。
func TestTraceTrimsPerRepo(t *testing.T) {
	s := dbStore(t)
	// 先灌满（直接写库，省掉一千次 autocommit），再让 Trace 走一次真实写入
	if _, err := s.db.Exec(`WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i+1 FROM n WHERE i<?)
		INSERT INTO project_traces(id,repo,branch,action,at) SELECT 'old-'||i,'/repo/a','b'||i,'merged',i FROM n`,
		traceKeep+19); err != nil {
		t.Fatal(err)
	}
	s.Trace(TraceEntry{Repo: "/repo/b", Branch: "keep-me", Action: "merged"})
	s.Trace(TraceEntry{Repo: "/repo/a", Branch: "newest", Action: "merged"})

	var n int
	if err := s.db.QueryRow(`SELECT COUNT(*) FROM project_traces WHERE repo='/repo/a'`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != traceKeep {
		t.Fatalf("应当修剪到 %d 条, got %d", traceKeep, n)
	}
	// 修剪掉的必须是最老的那些，而且别动别的仓库
	if got := s.ReadTrace("/repo/a", 1); len(got) != 1 || got[0].Branch != "newest" {
		t.Fatalf("最新那条不该被修剪掉: %+v", got)
	}
	// 被砍掉的是最老的那 20 条
	var oldest string
	if err := s.db.QueryRow(`SELECT branch FROM project_traces WHERE repo='/repo/a'
		ORDER BY at ASC LIMIT 1`).Scan(&oldest); err != nil {
		t.Fatal(err)
	}
	if oldest != "b21" {
		t.Fatalf("砍掉的应当是最老的那些，现存最老是 %q", oldest)
	}
	if got := s.ReadTrace("/repo/b", 10); len(got) != 1 {
		t.Fatalf("修剪串到别的仓库了: %+v", got)
	}
}

// 已在册的项目再「新建」一次（典型：从它的 worktree 目录建，归位到同一仓库根）：
// id 不变、不算新建，传来的名字不许盖掉项目本来的名字。
func TestAddExistingKeepsDisplayName(t *testing.T) {
	s := NewStore(t.TempDir(), nil)
	k, created := s.Add("/repo/blade-agent", "blade-agent")
	if !created {
		t.Fatal("第一次该是新建")
	}
	k2, created2 := s.Add("/repo/blade-agent", "blade-agent-sea-attack")
	if k2 != k || created2 {
		t.Fatalf("同目录再建应返回原 id 且不算新建: %q/%v vs %q", k2, created2, k)
	}
	if got := s.Name(k); got != "blade-agent" {
		t.Fatalf("项目名不该被盖掉: %q", got)
	}
	// 从来没起过名的，再建时给的名字可以补上
	k3, _ := s.Add("/repo/noname", "")
	s.Add("/repo/noname", "起个名")
	if got := s.Name(k3); got != "起个名" {
		t.Fatalf("没起过名的可以补: %q", got)
	}
}
