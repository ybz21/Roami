package worktree

import (
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// mkRepo 造一个带一次提交的普通仓库，返回根路径。
func mkRepo(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	run := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
		cmd.Env = append(scrubGitEnv(),
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return string(out)
	}
	run("init", "-b", "main")
	if err := os.WriteFile(filepath.Join(dir, "a.txt"), []byte("hello\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	run("add", ".")
	run("commit", "-m", "init")
	run("remote", "add", "origin", dir)
	return dir
}

func commitFile(t *testing.T, dir, name, content, msg string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(dir, name), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("git", "-C", dir, "add", ".")
	cmd.Env = scrubGitEnv()
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("add: %v %s", err, out)
	}
	cmd = exec.Command("git", "-C", dir, "commit", "-m", msg)
	cmd.Env = append(scrubGitEnv(),
		"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("commit: %v %s", err, out)
	}
}

// base 缺省应始终回到本地主干（main/master），不能是当前检出的 feature 分支
// （很多仓库没设 origin/HEAD，旧逻辑会兜底到 HEAD 分支）。
func TestDefaultBasePrefersMain(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	// 检出到 feature 分支再建 worktree（不传 base）
	cmd := exec.Command("git", "-C", repo, "checkout", "-q", "-b", "feat/wip")
	cmd.Env = scrubGitEnv()
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("checkout: %v %s", err, out)
	}
	resp, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "probe-base"})
	if err != nil {
		t.Fatal(err)
	}
	if resp.Base != "main" {
		t.Fatalf("default base = %q, want main", resp.Base)
	}
}

func TestCreateListRemove(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)

	resp, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/feat-x", Base: "main"})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if resp.Branch != "roam/feat-x" || resp.Base != "main" || resp.StartOid == "" {
		t.Fatalf("bad resp: %+v", resp)
	}
	if !strings.Contains(resp.Path, ".worktrees") {
		t.Fatalf("path not under .worktrees: %s", resp.Path)
	}
	// 同名再建 → 锁内分配 -2
	resp2, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/feat-x", Base: "main"})
	if err != nil {
		t.Fatalf("create2: %v", err)
	}
	if resp2.Branch != "roam/feat-x-2" {
		t.Fatalf("expected suffix branch, got %s", resp2.Branch)
	}
	// info/exclude 幂等追加
	b, _ := os.ReadFile(filepath.Join(repo, ".git", "info", "exclude"))
	if !strings.Contains(string(b), "/.worktrees/") {
		t.Fatalf("info/exclude missing entry: %s", b)
	}

	// list：身份/主 worktree 标记
	s.cache = map[string]listCache{} // 绕过缓存
	list, err := s.List(ctx, repo)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	if len(list) != 3 {
		t.Fatalf("want 3 worktrees, got %d", len(list))
	}
	var wt *Worktree
	for i := range list {
		if list[i].Branch == "roam/feat-x" {
			wt = &list[i]
		}
		if list[i].IsMain && list[i].Branch != "main" {
			t.Fatalf("main worktree mislabelled: %+v", list[i])
		}
	}
	if wt == nil || wt.Base != "main" || wt.External {
		t.Fatalf("roam worktree identity wrong: %+v", wt)
	}

	// 脏保护：未提交改动默认拒删
	if err := os.WriteFile(filepath.Join(resp.Path, "b.txt"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	err = s.Remove(ctx, RemoveReq{Path: resp.Path, IgnoreSessions: true})
	we, ok := err.(*Err)
	if !ok || we.Code != "WORKTREE_DIRTY" {
		t.Fatalf("want WORKTREE_DIRTY, got %v", err)
	}
	// force 删 + 删分支
	if err := s.Remove(ctx, RemoveReq{Path: resp.Path, ForceWorktree: true, DeleteBranch: true, IgnoreSessions: true}); err != nil {
		t.Fatalf("force remove: %v", err)
	}
	if branchExists(ctx, Repo{Root: repo}, "roam/feat-x") {
		t.Fatal("branch should be deleted")
	}
}

func TestExternalWorktreeBaseUnknown(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	ext := filepath.Join(repo, ".worktrees", "ext")
	cmd := exec.Command("git", "-C", repo, "worktree", "add", "-b", "hand-made", ext)
	cmd.Env = scrubGitEnv()
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("external add: %v %s", err, out)
	}
	list, err := s.List(ctx, repo)
	if err != nil {
		t.Fatal(err)
	}
	for _, w := range list {
		if w.Branch == "hand-made" {
			if !w.External || w.Base != "" {
				t.Fatalf("external worktree should have unknown base: %+v", w)
			}
			// base unknown → diff/merge 拒绝
			if _, err := s.DiffBase(ctx, w.Path); err == nil || err.(*Err).Code != "BASE_UNKNOWN" {
				t.Fatalf("diff should refuse: %v", err)
			}
			if _, err := s.Merge(ctx, MergeReq{Path: w.Path, Strategy: "merge"}); err == nil || err.(*Err).Code != "BASE_UNKNOWN" {
				t.Fatalf("merge should refuse: %v", err)
			}
			return
		}
	}
	t.Fatal("external worktree not listed")
}

func TestMergeSquashAndConflict(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)

	resp, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/ok", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	commitFile(t, resp.Path, "feat.txt", "feature\n", "feat")

	// squash 合并成功（base=main checkout 在主 worktree）
	mr, err := s.Merge(ctx, MergeReq{Path: resp.Path, Strategy: "squash"})
	if err != nil {
		t.Fatalf("squash: %v", err)
	}
	if mr.MergedOid == "" {
		t.Fatal("no merged oid")
	}
	if _, err := os.Stat(filepath.Join(repo, "feat.txt")); err != nil {
		t.Fatal("squash result missing in main worktree")
	}

	// 冲突：两边改同一文件
	c, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/conflict", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	commitFile(t, c.Path, "a.txt", "branch version\n", "branch change")
	commitFile(t, repo, "a.txt", "main version\n", "main change")

	_, err = s.Merge(ctx, MergeReq{Path: c.Path, Strategy: "merge"})
	we, ok := err.(*Err)
	if !ok || we.Code != "MERGE_CONFLICT" {
		t.Fatalf("want MERGE_CONFLICT, got %v", err)
	}
	files, _ := we.Extra["conflictFiles"].([]string)
	if len(files) != 1 || files[0] != "a.txt" {
		t.Fatalf("conflict files wrong: %v", we.Extra)
	}
	// abort 后主 worktree 干净、无半成品
	if !isClean(ctx, repo) {
		t.Fatal("main worktree left dirty after abort")
	}
	if p := inProgress(ctx, repo); p != "" {
		t.Fatalf("operation left in progress: %s", p)
	}

	// rebase 路径：解决 conflict 场景外的正常 rebase
	r, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/rebase", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	commitFile(t, r.Path, "r.txt", "r\n", "r change")
	commitFile(t, repo, "m.txt", "m\n", "advance main")
	if _, err := s.Merge(ctx, MergeReq{Path: r.Path, Strategy: "rebase"}); err != nil {
		t.Fatalf("rebase merge: %v", err)
	}
	if _, err := os.Stat(filepath.Join(repo, "r.txt")); err != nil {
		t.Fatal("rebase ff result missing")
	}
}

// 远端分支：Branches 列出 remote-tracking 分支（结构化拆 remote/name，含 / 的
// 分支名不靠字符串猜），Create 可基于本地不存在、仅远端有的分支建 worktree。
func TestBranchesAndCreateFromRemote(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	upstream := mkRepo(t)
	gitIn := func(dir string, args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
		cmd.Env = append(scrubGitEnv(),
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return string(out)
	}
	// 上游造一个仅远端存在的分支（带 /，验证切分）
	gitIn(upstream, "checkout", "-q", "-b", "feat/remote-only")
	commitFile(t, upstream, "remote.txt", "r\n", "remote change")
	gitIn(upstream, "checkout", "-q", "main")

	local := mkRepo(t)
	gitIn(local, "remote", "set-url", "origin", upstream)
	gitIn(local, "fetch", "-q", "origin")
	// 歧义引用名：本地分支恰叫 origin/main 时 %(refname:short) 会输出
	// remotes/origin/main——远端分支不能因此被漏掉
	gitIn(local, "branch", "origin/main")

	_, _, remotes, err := s.Branches(ctx, local)
	if err != nil {
		t.Fatalf("branches: %v", err)
	}
	foundFeat, foundMain := false, false
	for _, rb := range remotes {
		if rb.Remote == "origin" && rb.Name == "feat/remote-only" {
			foundFeat = true
		}
		if rb.Remote == "origin" && rb.Name == "main" {
			foundMain = true
		}
		if rb.Name == "HEAD" {
			t.Fatalf("HEAD should be skipped: %+v", remotes)
		}
	}
	if !foundFeat {
		t.Fatalf("origin/feat/remote-only not listed: %+v", remotes)
	}
	if !foundMain {
		t.Fatalf("origin/main dropped under ambiguous local branch name: %+v", remotes)
	}

	// 基于远端分支建 worktree：本地无 feat/remote-only，Create fetch 后锁 OID
	resp, err := s.Create(ctx, CreateReq{Dir: local, Branch: "roam/from-remote", Base: "feat/remote-only", Remote: "origin"})
	if err != nil {
		t.Fatalf("create from remote: %v", err)
	}
	tip := strings.TrimSpace(gitIn(upstream, "rev-parse", "feat/remote-only"))
	if resp.StartOid != tip {
		t.Fatalf("start oid = %s, want upstream tip %s", resp.StartOid, tip)
	}
	if _, err := os.Stat(filepath.Join(resp.Path, "remote.txt")); err != nil {
		t.Fatal("worktree missing file from remote branch")
	}
}

func TestExpectedHeadGuard(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	resp, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/drift", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	commitFile(t, resp.Path, "d.txt", "d\n", "d")
	_, err = s.Merge(ctx, MergeReq{Path: resp.Path, Strategy: "merge", ExpectedHead: "deadbeef"})
	if we, ok := err.(*Err); !ok || we.Code != "HEAD_MOVED" {
		t.Fatalf("want HEAD_MOVED, got %v", err)
	}
}

// 合入检测（10 设计 §4）：远端 merge/squash 后，本地 base 不 pull 也要能翻绿；
// 远端分支被删（branch-gone）只作佐证标记。全程用本地 bare 仓库当 origin，离线可跑。
func TestMergedDetection(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	gitIn := func(dir string, args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
		cmd.Env = append(scrubGitEnv(),
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	origin := filepath.Join(t.TempDir(), "origin.git")
	gitIn(repo, "clone", "--bare", repo, origin)
	gitIn(repo, "remote", "set-url", "origin", origin)

	find := func(path string) Worktree {
		t.Helper()
		s.invalidate(Repo{CommonDir: canonical(filepath.Join(repo, ".git"))})
		list, err := s.List(ctx, repo)
		if err != nil {
			t.Fatal(err)
		}
		for _, w := range list {
			if w.Path == path {
				return w
			}
		}
		t.Fatalf("worktree %s not in list", path)
		return Worktree{}
	}

	// ── 空 worktree：新建即秒判「已合入」的回归（HEAD==base tip，是 target 祖先）──
	we, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/empty", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	if w := find(we.Path); w.MergedInto != "" {
		t.Fatalf("empty worktree must NOT be merged, got %+v", w)
	}

	// ── S1 祖先：远端 main fast-forward 到任务分支，本地 main 不动 ──
	wa, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/feat-a", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	commitFile(t, wa.Path, "a2.txt", "a2\n", "feat a")
	headA := gitIn(wa.Path, "rev-parse", "HEAD")
	if w := find(wa.Path); w.MergedInto != "" {
		t.Fatalf("before sync: unexpectedly merged: %+v", w)
	}
	gitIn(repo, "push", "-q", "origin", "roam/feat-a")
	gitIn(origin, "update-ref", "refs/heads/main", headA) // 远端「merge」（对象已随 push 到位）
	if res, err := s.Sync(ctx, repo); err != nil || res.Error != "" || res.SyncedAt == 0 {
		t.Fatalf("sync: %v %+v", err, res)
	}
	w := find(wa.Path)
	if w.MergedInto != "origin/main" || w.MergedKind != "ancestry" {
		t.Fatalf("S1 want merged ancestry into origin/main, got %+v", w)
	}
	if w.RemoteGone {
		t.Fatalf("S1: branch still on remote, gone=false expected: %+v", w)
	}

	// ── S3 branch-gone：远端删掉任务分支后再 Sync ──
	gitIn(origin, "update-ref", "-d", "refs/heads/roam/feat-a")
	if _, err := s.Sync(ctx, repo); err != nil {
		t.Fatal(err)
	}
	if w := find(wa.Path); !w.RemoteGone {
		t.Fatalf("S3 want remoteGone after remote branch deleted, got %+v", w)
	}

	// ── S2 补丁等价（squash）：远端 main 上是同补丁的新提交 ──
	wb, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/feat-b", Base: "main", Remote: "origin"})
	if err != nil {
		t.Fatal(err)
	}
	commitFile(t, wb.Path, "b.txt", "b\n", "feat b")
	headB := gitIn(wb.Path, "rev-parse", "HEAD")
	remoteMain := gitIn(origin, "rev-parse", "refs/heads/main")
	squash := gitIn(repo, "commit-tree", headB+"^{tree}", "-p", remoteMain, "-m", "squash: feat b (#1)")
	gitIn(repo, "push", "-q", "origin", squash+":refs/heads/main") // 远端「squash 合并」
	if _, err := s.Sync(ctx, repo); err != nil {
		t.Fatal(err)
	}
	w = find(wb.Path)
	if w.MergedInto != "origin/main" || w.MergedKind != "squash" {
		t.Fatalf("S2 want merged squash, got %+v", w)
	}
	if w.AheadUnique != 0 {
		t.Fatalf("S2 want aheadUnique=0, got %d", w.AheadUnique)
	}

	// ── 未合并的真领先：分支再长一个新提交 → 翻回未合并，aheadUnique=1 ──
	commitFile(t, wb.Path, "b2.txt", "b2\n", "feat b followup")
	w = find(wb.Path)
	if w.MergedInto != "" {
		t.Fatalf("followup commit must flip back to unmerged, got %+v", w)
	}
	if w.AheadUnique != 1 {
		t.Fatalf("want aheadUnique=1 after followup, got %d", w.AheadUnique)
	}
}

// 分叉点(StartOid)守空 worktree：base 仅在远端、本地无 refs/heads/<base> 时，旧
// 「相对本地 base 有无独占提交」的兜底判据会退化成放行——空 worktree HEAD==远端 base
// tip，又是 origin/<base> 的祖先，S1 秒判「已合入」。改用 Head==StartOid 判 ownWork
// 后与本地 base ref 是否存在无关，空 worktree 恒不合入。
func TestMergedEmptyWorktreeRemoteOnlyBase(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	gitIn := func(dir string, args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
		cmd.Env = append(scrubGitEnv(),
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	origin := filepath.Join(t.TempDir(), "origin.git")
	gitIn(repo, "clone", "--bare", repo, origin)
	gitIn(repo, "remote", "set-url", "origin", origin)
	// base 分支只留在远端：本地建 relbase→推送→删本地，制造「无 refs/heads/relbase」
	gitIn(repo, "branch", "relbase")
	gitIn(repo, "push", "-q", "origin", "relbase")
	gitIn(repo, "branch", "-D", "relbase")

	// 从远端 relbase 建空 worktree（Remote 走 fetch 锁 OID），一行未改
	wt, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/rel", Base: "relbase", Remote: "origin"})
	if err != nil {
		t.Fatal(err)
	}
	s.invalidate(Repo{CommonDir: canonical(filepath.Join(repo, ".git"))})
	list, err := s.List(ctx, repo)
	if err != nil {
		t.Fatal(err)
	}
	for _, w := range list {
		if w.Path == wt.Path {
			if w.MergedInto != "" {
				t.Fatalf("empty worktree on remote-only base must NOT be merged, got %+v", w)
			}
			return
		}
	}
	t.Fatalf("worktree %s not in list", wt.Path)
}

// 三态细化（已提交→已推送→已合入）：Pushed 靠本地 origin/<branch> 跟踪 ref 判定。
// 关键前提是 `git push` 成功后会更新对应 remote-tracking ref（git ≥1.8.4），故无需联网
// 也无需 Sync 抓任务分支——本测试用本地 bare 当 origin 全程离线验证这条通路。
func TestPushedDetection(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	gitIn := func(dir string, args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
		cmd.Env = append(scrubGitEnv(),
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	origin := filepath.Join(t.TempDir(), "origin.git")
	gitIn(repo, "clone", "--bare", repo, origin)
	gitIn(repo, "remote", "set-url", "origin", origin)

	find := func(path string) Worktree {
		t.Helper()
		s.invalidate(Repo{CommonDir: canonical(filepath.Join(repo, ".git"))})
		list, err := s.List(ctx, repo)
		if err != nil {
			t.Fatal(err)
		}
		for _, w := range list {
			if w.Path == path {
				return w
			}
		}
		t.Fatalf("worktree %s not in list", path)
		return Worktree{}
	}

	wt, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/feat-p", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	commitFile(t, wt.Path, "p.txt", "p\n", "feat p")

	// 本地已提交、未推送：Pushed=false（origin/roam/feat-p 跟踪 ref 尚不存在）
	if w := find(wt.Path); w.Pushed {
		t.Fatalf("before push: want pushed=false, got %+v", w)
	}

	// push 成功后 remote-tracking ref 更新 → Pushed=true，但未合入（MergedInto 为空）
	gitIn(wt.Path, "push", "-q", "origin", "roam/feat-p")
	w := find(wt.Path)
	if !w.Pushed {
		t.Fatalf("after push: want pushed=true, got %+v", w)
	}
	if w.MergedInto != "" {
		t.Fatalf("after push: still unmerged expected, got %+v", w)
	}

	// 推送后又长新提交 → HEAD 不再是 origin 祖先 → 翻回未推送
	commitFile(t, wt.Path, "p2.txt", "p2\n", "feat p followup")
	if w := find(wt.Path); w.Pushed {
		t.Fatalf("after local followup: want pushed=false, got %+v", w)
	}
}

// 半删残缺态自愈（10 §7 实测）：git 删工作树半路失败会留下 gitfile 已删、注册表
// 还在的卡死状态——Remove(force) 应能从父目录解析仓库并 RemoveAll+prune 收干净。
func TestRemoveHalfDeadWorktree(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	wt, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "roam/half-dead", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	// 模拟半删：gitfile 没了、目录里还剩东西
	if err := os.Remove(filepath.Join(wt.Path, ".git")); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(wt.Path, "leftover.txt"), []byte("x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := s.Remove(ctx, RemoveReq{Path: wt.Path, ForceWorktree: true, IgnoreSessions: true}); err != nil {
		t.Fatalf("remove half-dead: %v", err)
	}
	if pathExists(wt.Path) {
		t.Fatal("worktree dir should be gone")
	}
	out, err := exec.Command("git", "-C", repo, "worktree", "list", "--porcelain").CombinedOutput()
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(out), wt.Path) {
		t.Fatalf("registry entry should be pruned:\n%s", out)
	}
}

// Dirname 指定目录名：分支名可以撞（中文标题一律派生成 "task"），目录不能撞——
// 撞了就是新旧两个任务共用一个工作区。传会话 id 后两次创建各自落在自己的目录里。
func TestCreateDirnameSeparatesSameBranch(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)

	a, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "task", Base: "main", Dirname: "2026-0807-2143-002m"})
	if err != nil {
		t.Fatalf("create a: %v", err)
	}
	b, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "task", Base: "main", Dirname: "2026-0807-2201-002n"})
	if err != nil {
		t.Fatalf("create b: %v", err)
	}
	if filepath.Base(a.Path) != "2026-0807-2143-002m" || filepath.Base(b.Path) != "2026-0807-2201-002n" {
		t.Fatalf("dirname ignored: %s / %s", a.Path, b.Path)
	}
	// 分支仍按老规矩加序号；目录不该跟着分支走
	if a.Branch != "task" || b.Branch != "task-2" {
		t.Fatalf("branch alloc changed: %s / %s", a.Branch, b.Branch)
	}
	// 收尾释放 task 目录后，新任务不该原地复用它
	if err := s.Remove(ctx, RemoveReq{Path: a.Path}); err != nil {
		t.Fatalf("remove: %v", err)
	}
	c, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "task", Base: "main", Dirname: "2026-0807-2230-002p"})
	if err != nil {
		t.Fatalf("create c: %v", err)
	}
	if c.Path == a.Path {
		t.Fatalf("recycled removed worktree path: %s", c.Path)
	}
}

// 不传 Dirname 时沿用分支 slug（/git/worktree 直建口径不变）。
func TestCreateWithoutDirnameKeepsBranchSlug(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	resp, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "feat/x", Base: "main"})
	if err != nil {
		t.Fatalf("create: %v", err)
	}
	if filepath.Base(resp.Path) != "feat-x" {
		t.Fatalf("path = %s, want .worktrees/feat-x", resp.Path)
	}
}

// 「已有」不只有 worktree：为一条**既有本地分支**开工作区 = 检出它，不新建分支。
// 起点记与 base 的分叉点（记成分支尖端的话，分支上已有的提交会被算成「没干过活」），
// 并打 adopted 标记——收尾时不该把用户自己的分支顺手删了。
func TestCreateAdoptsExistingBranch(t *testing.T) {
	ctx := context.Background()
	s := New("", nil)
	repo := mkRepo(t)
	g := func(dir string, args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
		cmd.Env = append(scrubGitEnv(),
			"GIT_AUTHOR_NAME=t", "GIT_AUTHOR_EMAIL=t@t", "GIT_COMMITTER_NAME=t", "GIT_COMMITTER_EMAIL=t@t")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	g(repo, "checkout", "-q", "-b", "feat/old")
	commitFile(t, repo, "old.txt", "x\n", "old work")
	tip := g(repo, "rev-parse", "HEAD")
	g(repo, "checkout", "-q", "main")
	fork := g(repo, "merge-base", "main", "feat/old")

	resp, err := s.Create(ctx, CreateReq{Dir: repo, Branch: "feat/old", Base: "main", Existing: true, Dirname: "sess-1"})
	if err != nil {
		t.Fatalf("adopt: %v", err)
	}
	if resp.Branch != "feat/old" {
		t.Fatalf("branch = %q, want feat/old (no new branch)", resp.Branch)
	}
	if resp.StartOid != fork {
		t.Fatalf("startOid = %s, want fork point %s", resp.StartOid, fork)
	}
	if got := g(resp.Path, "rev-parse", "HEAD"); got != tip {
		t.Fatalf("worktree HEAD = %s, want branch tip %s", got, tip)
	}

	s.cache = map[string]listCache{}
	list, err := s.List(ctx, repo)
	if err != nil {
		t.Fatalf("list: %v", err)
	}
	var wt *Worktree
	for i := range list {
		if list[i].Branch == "feat/old" {
			wt = &list[i]
		}
	}
	if wt == nil || !wt.Adopted || wt.External || wt.Base != "main" {
		t.Fatalf("adopted worktree identity wrong: %+v", wt)
	}

	// 已被检出的分支收养不了：main 在主仓库、feat/old 在刚建的 worktree
	for _, b := range []string{"feat/old", "main"} {
		_, err := s.Create(ctx, CreateReq{Dir: repo, Branch: b, Base: "main", Existing: true, Dirname: "sess-2"})
		we, ok := err.(*Err)
		if !ok || we.Code != "BRANCH_CHECKED_OUT" {
			t.Fatalf("adopt %s again: want BRANCH_CHECKED_OUT, got %v", b, err)
		}
	}
	// 不存在的分支不许凭空建出来（那是「新建」档的事）
	_, err = s.Create(ctx, CreateReq{Dir: repo, Branch: "nope", Base: "main", Existing: true, Dirname: "sess-3"})
	if we, ok := err.(*Err); !ok || we.Code != "BAD_BRANCH" {
		t.Fatalf("adopt missing branch: want BAD_BRANCH, got %v", err)
	}

	// Branches 要把「谁占着这条分支」一并给出来：选择器据此不把占用中的分支当候选
	bs, _, _, err := s.Branches(ctx, repo)
	if err != nil {
		t.Fatalf("branches: %v", err)
	}
	seen := map[string]LocalBranch{}
	for _, b := range bs {
		seen[b.Name] = b
	}
	if got := seen["feat/old"]; canonical(got.Worktree) != canonical(resp.Path) {
		t.Fatalf("feat/old worktree = %q, want %q", got.Worktree, resp.Path)
	}
	if got := seen["main"]; canonical(got.Worktree) != canonical(repo) || got.LastCommitAt == 0 {
		t.Fatalf("main branch meta wrong: %+v", got)
	}
}
