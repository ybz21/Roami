package sessmeta

import (
	"testing"
	"time"
)

// newTestStore 造一个带假 tmux 映射的 store；改 ids 即模拟建/杀/改名会话。
func newTestStore(t *testing.T, ids map[string]string) (*Store, func(map[string]string)) {
	t.Helper()
	dir := t.TempDir()
	cur := ids
	s := New(dir)
	s.Now = func() time.Time { return time.Date(2026, 7, 28, 11, 13, 0, 0, time.UTC) }
	s.WithIDs(func() map[string]string { return cur })
	return s, func(next map[string]string) { cur = next; s.invalidate() }
}

func TestPutParentChildren(t *testing.T) {
	s, _ := newTestStore(t, map[string]string{"dad": "$1", "kid": "$2"})
	if err := s.Put(Row{Session: "kid", Parent: "dad", CreatedBy: "fork", InitialCwd: "/repo"}); err != nil {
		t.Fatal(err)
	}
	if got := s.Parent("kid"); got != "dad" {
		t.Fatalf("Parent = %q, want dad", got)
	}
	if got := s.Children("dad"); len(got) != 1 || got[0] != "kid" {
		t.Fatalf("Children = %v, want [kid]", got)
	}
	all := s.All()
	if r, ok := all["kid"]; !ok || r.Parent != "dad" || r.InitialCwd != "/repo" || r.CreatedBy != "fork" {
		t.Fatalf("All = %+v", all)
	}
}

// 父会话往往是 `roami session new` 直建的、自己没有行（只有 fork 出来的孩子才写行）。
// 投影必须按 tmux 实况认爹，按「表里有没有活行」认会把整棵树拍平。
func TestParentWithoutOwnRowKeepsTree(t *testing.T) {
	s, _ := newTestStore(t, map[string]string{"dad": "$1", "kid": "$2"})
	if err := s.Put(Row{Session: "kid", Parent: "dad", CreatedBy: "fork"}); err != nil {
		t.Fatal(err)
	}
	if got := s.All()["kid"].Parent; got != "dad" {
		t.Fatalf("父没有自己的行时也该挂在它下面，got %q", got)
	}
}

// 会话名就是主键：tmux 盲态下也照记不误。以前要先问出 `$N` 才肯写，
// 于是盲态那一笔元数据永远丢了。
func TestPutWorksWhenBlind(t *testing.T) {
	s, _ := newTestStore(t, nil)
	if err := s.Put(Row{Session: "ghost", CreatedBy: "fork", InitialCwd: "/repo"}); err != nil {
		t.Fatalf("盲态也该记得住: %v", err)
	}
	if got := s.All()["ghost"].InitialCwd; got != "/repo" {
		t.Fatalf("盲态写入丢字段: %+v", s.All())
	}
	if err := s.Put(Row{Session: ""}); err == nil {
		t.Fatal("会话名为空必须报错")
	}
}

// 日常改名只动 @roam_name，会话名（= 持久 id）不变，树自然不受影响。
// 真改了 tmux 会话名（MigrateSessionsToID 那类一次性迁移）则主键跟着搬。
func TestRenameMovesKey(t *testing.T) {
	s, setIDs := newTestStore(t, map[string]string{"dad": "$1", "kid": "$2"})
	if err := s.Put(Row{Session: "kid", Parent: "dad"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(Row{Session: "dad", CreatedBy: "new"}); err != nil {
		t.Fatal(err)
	}
	setIDs(map[string]string{"dad-v2": "$1", "kid": "$2"})
	if err := s.OnRename("dad", "dad-v2"); err != nil {
		t.Fatal(err)
	}
	if got := s.Parent("kid"); got != "dad-v2" {
		t.Fatalf("改名后 Parent = %q, want dad-v2", got)
	}
	if got := s.Children("dad-v2"); len(got) != 1 || got[0] != "kid" {
		t.Fatalf("改名后 Children = %v", got)
	}
	if got := s.All()["kid"].Parent; got != "dad-v2" {
		t.Fatalf("All 投影 Parent = %q", got)
	}
}

// 同名复用（`_ttmux-*` 单例、固定名插件会话）：旧会话死了、新会话叫同一个名字
// → 收敛时复活成一行**干净的**新记录，不继承任何旧来历。
func TestSameNameReuseDoesNotInherit(t *testing.T) {
	s, setIDs := newTestStore(t, map[string]string{"dad": "$1", "kid": "$2"})
	if err := s.Put(Row{Session: "kid", Parent: "dad", InitialCwd: "/old"}); err != nil {
		t.Fatal(err)
	}
	setIDs(map[string]string{"dad": "$1"}) // kid 被杀
	s.Reconcile(map[string]bool{"dad": true})
	setIDs(map[string]string{"dad": "$1", "kid": "$9"}) // 同名重建
	s.Reconcile(map[string]bool{"dad": true, "kid": true})
	if got := s.Parent("kid"); got != "" {
		t.Fatalf("新会话不该继承旧 parent，got %q", got)
	}
	if got := s.All()["kid"].InitialCwd; got != "" {
		t.Fatalf("新会话不该继承旧起始目录，got %q", got)
	}
	if got := s.Children("dad"); len(got) != 0 {
		t.Fatalf("旧关系不该还算数，got %v", got)
	}
}

// OnKill：行不删，只置 dead。孩子在投影里成孤儿，但表里「谁 fork 出了谁」保住。
func TestOnKillKeepsHistory(t *testing.T) {
	s, setIDs := newTestStore(t, map[string]string{"dad": "$1", "kid": "$2"})
	if err := s.Put(Row{Session: "kid", Parent: "dad"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(Row{Session: "dad", CreatedBy: "new", InitialCwd: "/repo"}); err != nil {
		t.Fatal(err)
	}
	setIDs(map[string]string{"kid": "$2"}) // dad 已被杀
	if err := s.OnKill("dad"); err != nil {
		t.Fatal(err)
	}
	if _, ok := s.All()["dad"]; ok {
		t.Fatal("死会话不该出现在活会话投影里")
	}
	if got := s.All()["kid"].Parent; got != "" {
		t.Fatalf("父死后孩子在投影里应成孤儿，got %q", got)
	}
	if got := s.Parent("kid"); got != "dad" {
		t.Fatalf("表里的来历不该被父亲的死改写，got %q", got)
	}
	hist := s.History(0)
	if len(hist) != 1 || hist[0].Session != "dad" || hist[0].InitialCwd != "/repo" {
		t.Fatalf("死会话应进历史且字段完整: %+v", hist)
	}
	if hist[0].DiedReason != "killed" {
		t.Fatalf("died_reason = %q, want killed", hist[0].DiedReason)
	}
}

func TestReconcile(t *testing.T) {
	s, setIDs := newTestStore(t, map[string]string{"dad": "$1", "kid": "$2"})
	if err := s.Put(Row{Session: "kid", Parent: "dad"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(Row{Session: "dad"}); err != nil {
		t.Fatal(err)
	}
	// tmux 盲态（alive 空）：一行不许动
	s.Reconcile(nil)
	if len(s.All()) != 2 {
		t.Fatalf("盲态下不该收敛: %+v", s.All())
	}
	// dad 被裸 tmux kill 掉：收敛后 kid 在投影里成孤儿，dad 进历史而不是被删
	setIDs(map[string]string{"kid": "$2"})
	s.Reconcile(map[string]bool{"kid": true})
	if got := s.All()["kid"].Parent; got != "" {
		t.Fatalf("收敛后 kid 应是孤儿，got %q", got)
	}
	if hist := s.History(0); len(hist) != 1 || hist[0].Session != "dad" {
		t.Fatalf("dad 应进历史而不是被删: %+v", hist)
	}
	// 会话回来了（之前是收敛误判/tmux 抽风）：自愈回 live
	setIDs(map[string]string{"kid": "$2", "dad": "$1"})
	s.Reconcile(map[string]bool{"kid": true, "dad": true})
	if _, ok := s.All()["dad"]; !ok {
		t.Fatal("会话回来后应自愈回 live")
	}
	if len(s.History(0)) != 0 {
		t.Fatalf("自愈后不该还留在历史里: %+v", s.History(0))
	}
}

// 机器重启：tmux server 换代，所有会话一起消失。整表必须原样留着（这正是
// 「重启后会话全没了」的病根），并且记成 host-restart 而不是 killed。
func TestHostRestartKeepsEverything(t *testing.T) {
	s, setIDs := newTestStore(t, map[string]string{"dad": "$1", "kid": "$2"})
	s.Epoch = func() string { return "1000" }
	if err := s.Put(Row{Session: "kid", Parent: "dad", InitialCwd: "/repo"}); err != nil {
		t.Fatal(err)
	}
	if err := s.Put(Row{Session: "dad", InitialCwd: "/repo"}); err != nil {
		t.Fatal(err)
	}
	// 重启后：tmux 换了 server，`$N` 从 $0 重新发号给了两个全新的会话
	s.Epoch = func() string { return "2000" }
	setIDs(map[string]string{"fresh": "$1"})
	s.Reconcile(map[string]bool{"fresh": true})

	hist := s.History(0)
	if len(hist) != 2 {
		t.Fatalf("重启不该让历史消失，got %+v", hist)
	}
	for _, r := range hist {
		if r.DiedReason != "host-restart" {
			t.Fatalf("%s died_reason = %q, want host-restart", r.Session, r.DiedReason)
		}
		if r.InitialCwd != "/repo" {
			t.Fatalf("%s 丢了归属目录", r.Session)
		}
	}
	// 新会话拿到了旧的 `$1`，但绝不该继承旧会话的任何关系
	if got := s.Parent("fresh"); got != "" {
		t.Fatalf("新会话继承了死会话的 parent: %q", got)
	}
}

// 死行按保留上限收口，读放大有界。
func TestPruneBoundsDeadRows(t *testing.T) {
	s, setIDs := newTestStore(t, map[string]string{"a": "$1", "b": "$2", "c": "$3"})
	for i, n := range []string{"a", "b", "c"} {
		if err := s.Put(Row{Session: n, CreatedAt: time.Date(2026, 7, 1+i, 0, 0, 0, 0, time.UTC).Format(time.RFC3339)}); err != nil {
			t.Fatal(err)
		}
	}
	setIDs(map[string]string{"c": "$3"})
	s.Reconcile(map[string]bool{"c": true})
	db, err := s.db()
	if err != nil {
		t.Fatal(err)
	}
	s.prune(db, 1)
	var n int
	if err := db.QueryRow(`SELECT COUNT(*) FROM sessions WHERE status='dead'`).Scan(&n); err != nil {
		t.Fatal(err)
	}
	if n != 1 {
		t.Fatalf("prune 后死行 = %d, want 1", n)
	}
}

// Put 曾经用 INSERT OR REPLACE —— 那是 DELETE+INSERT、整行重置。
// sessions 上还有别处写的列（home_dir / repo_root / label），一旦被 Put 抹掉，
// 「重开」拿到的就永远是空壳。这条钉死它不会再回去。
func TestPutKeepsColumnsWrittenElsewhere(t *testing.T) {
	s, _ := newTestStore(t, map[string]string{"kid": "$2"})
	if err := s.Put(Row{Session: "kid", CreatedBy: "new"}); err != nil {
		t.Fatal(err)
	}
	if err := s.SetHome("kid", "/repo/a", "/repo"); err != nil {
		t.Fatal(err)
	}
	if err := s.SetLabel("kid", "我的会话"); err != nil {
		t.Fatal(err)
	}
	// 再 Put 一次（fork / plugin 建会话 / adopt 都会这么干）
	if err := s.Put(Row{Session: "kid", CreatedBy: "fork", Parent: "dad"}); err != nil {
		t.Fatal(err)
	}
	db, err := s.db()
	if err != nil {
		t.Fatal(err)
	}
	var home, repo, label string
	err = db.QueryRow(`SELECT IFNULL(home_dir,''), IFNULL(repo_root,''), IFNULL(label,'')
		FROM sessions WHERE id='kid'`).Scan(&home, &repo, &label)
	if err != nil {
		t.Fatal(err)
	}
	if home != "/repo/a" || repo != "/repo" || label != "我的会话" {
		t.Fatalf("Put 抹掉了别处写的列: home=%q repo=%q label=%q", home, repo, label)
	}
	// 而 Put 自己那几列要照常更新
	if got := s.Parent("kid"); got != "dad" {
		t.Fatalf("Put 该更新的列没更新, parent=%q", got)
	}
}

// SetHome 是**显式改钉**（后端 cdInto / fork 继承之后会调），非空值该覆盖；
// 但传空表示「这一项我没有」，不能因此清掉已经记下的事实。
func TestSetHomeOverwritesButBlankKeeps(t *testing.T) {
	s, _ := newTestStore(t, map[string]string{"kid": "$2"})
	if err := s.SetHome("kid", "/first", "/repo"); err != nil {
		t.Fatal(err)
	}
	if err := s.SetHome("kid", "/second", ""); err != nil {
		t.Fatal(err)
	}
	db, _ := s.db()
	var home, repo string
	db.QueryRow(`SELECT IFNULL(home_dir,''), IFNULL(repo_root,'') FROM sessions WHERE id='kid'`).Scan(&home, &repo)
	if home != "/second" {
		t.Fatalf("显式改钉应当覆盖, got %q", home)
	}
	if repo != "/repo" {
		t.Fatalf("传空不该清掉已有的 repo_root: %q", repo)
	}
}

// tmux server 整个不在（重启 / kill-server）：这不是盲态，所有 live 行一次收进历史，
// 记 host-restart、died_at 取最后一次看见它，并且**当场**就出现在 Dormant() 里——
// 不用等用户新建一个会话让 alive 非空才被收敛。
func TestServerGoneMarksLiveRowsDormant(t *testing.T) {
	s, _ := newTestStore(t, map[string]string{"a": "$1", "b": "$2"})
	s.Epoch = func() string { return "1000" }
	dir := t.TempDir()
	for _, n := range []string{"a", "b"} {
		if err := s.Put(Row{Session: n, InitialCwd: dir}); err != nil {
			t.Fatal(err)
		}
	}
	// 活着时看见过一次：died_at 应取这一刻，不是之后收敛的时刻
	s.Reconcile(map[string]bool{"a": true, "b": true})
	seen := s.Now().Format(time.RFC3339)
	s.Now = func() time.Time { return time.Date(2026, 7, 29, 9, 0, 0, 0, time.UTC) }

	s.ReconcileServerGone()

	if live := s.All(); len(live) != 0 {
		t.Fatalf("server 没了不该还有活行: %+v", live)
	}
	hist := s.History(0)
	if len(hist) != 2 {
		t.Fatalf("两行都该进历史，got %+v", hist)
	}
	for _, r := range hist {
		if r.DiedReason != "host-restart" {
			t.Fatalf("%s died_reason = %q, want host-restart", r.Session, r.DiedReason)
		}
		if r.DiedAt != seen {
			t.Fatalf("%s died_at = %q, want 最后一次看见 %q", r.Session, r.DiedAt, seen)
		}
	}
	if got := s.Dormant(); len(got) != 2 {
		t.Fatalf("server 没了之后休眠列表就该有它们，got %+v", got)
	}
	// 没有活行时再来一次什么都不变
	s.ReconcileServerGone()
	if len(s.History(0)) != 2 || len(s.Dormant()) != 2 {
		t.Fatalf("重复收敛不该改变结果: %+v", s.History(0))
	}
}
