// Package worktree 是 Worktree 领域服务：独占一切 git worktree 操作
// （create/list/diff/merge/remove/prune + 仓库锁）。设计见
// docs/design/web/07-worktree.md §2.3——ttmux CLI 只管 session，不理解 worktree；
// HTTP handler 只做薄转发，编排（建 worktree→建会话→失败补偿）在上层组合 API。
//
// 硬规则（评审 P0/P1）：
//   - 仓库身份 = canonical git-common-dir；所有写操作持 common-dir 级 flock。
//   - base 真相源写 worktree-local config（roam.baseref/startoid/createdby/createdat），
//     外部 worktree 无字段即 base=unknown，禁止一键合并。
//   - 最终 branch/path 在锁内分配；ref 输入过 check-ref-format / rev-parse --verify。
//   - merge 执行位 = checkout 了 base 的 worktree，找不到建临时 integration worktree；
//     三种 strategy 语义分开；冲突分别 abort 并返回 {stage, conflictFiles}。
//   - 读接口无写副作用（prune 显式）；ahead 指「未合并到 base」，与推送无关。
package worktree

import (
	"context"
	"fmt"
	"github.com/ybz21/Roami/internal/gitcontext"
	"github.com/ybz21/Roami/internal/metadb"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// ── 错误模型 ──────────────────────────────────────────────

type Err struct {
	Code    string         `json:"code"`
	Message string         `json:"message"`
	Extra   map[string]any `json:"extra,omitempty"`
}

func (e *Err) Error() string { return e.Code + ": " + e.Message }

func errf(code, format string, a ...any) *Err {
	return &Err{Code: code, Message: fmt.Sprintf(format, a...)}
}

// ── 服务与仓库解析 ────────────────────────────────────────

type Service struct {
	mu     sync.Mutex
	cache  map[string]listCache   // key: commonDir
	remote map[string]remoteState // key: commonDir（Sync 的远端观测，进程内缓存）
	homes  *homeStore             // session → 钉死的归属目录（见 sessionhome.go）
}

type listCache struct {
	at   time.Time
	data []Worktree
}

// remoteState 一次 Sync 的远端观测（10 设计 §3/§4 S3）：heads = ls-remote 到的
// 远端分支集合，用于 branch-gone 判定；nil = 尚未成功观测，S3 静默退化不报 gone。
type remoteState struct {
	at    time.Time
	err   string
	heads map[string]bool
}

// New 建服务；db 直连可用时会话归属走 session_homes 表，否则退回 JSON，
// dataDir 也为空则纯内存（测试用）。生产由 api.New 传入。
func New(dataDir string, db *metadb.DB) *Service {
	return &Service{cache: map[string]listCache{}, remote: map[string]remoteState{}, homes: newHomeStore(dataDir, db)}
}

const listCacheTTL = 3 * time.Second

// scrubGitEnv 去掉环境里的 GIT_*（GIT_DIR/GIT_INDEX_FILE/GIT_WORK_TREE…）：
// 进程若诞生于 git 钩子或被设置过这些变量，子进程 git 会被劫持到错误仓库。
func scrubGitEnv() []string {
	return gitcontext.ForDirectory(os.Environ())
}

func git(ctx context.Context, dir string, args ...string) (string, error) {
	full := append([]string{"-C", dir, "-c", "core.quotepath=false"}, args...)
	cmd := exec.CommandContext(ctx, "git", full...)
	cmd.Env = append(scrubGitEnv(), "GIT_TERMINAL_PROMPT=0")
	out, err := cmd.CombinedOutput()
	return strings.TrimRight(string(out), "\n"), err
}

// gitID 同 git()，用于会产生提交的操作（merge/squash commit/rebase/wip commit）：
// 仓库连全局都没配 user.name/email 时（CI、裸机），注入 roam 机器身份兜底——
// 只在 `git var GIT_AUTHOR_IDENT` 解析失败时注入，绝不覆盖用户已配置的身份。
func gitID(ctx context.Context, dir string, args ...string) (string, error) {
	full := append([]string{"-C", dir, "-c", "core.quotepath=false"}, args...)
	cmd := exec.CommandContext(ctx, "git", full...)
	cmd.Env = append(scrubGitEnv(), "GIT_TERMINAL_PROMPT=0")
	if _, err := git(ctx, dir, "var", "GIT_AUTHOR_IDENT"); err != nil {
		cmd.Env = append(cmd.Env,
			"GIT_AUTHOR_NAME=roam", "GIT_AUTHOR_EMAIL=roam@localhost",
			"GIT_COMMITTER_NAME=roam", "GIT_COMMITTER_EMAIL=roam@localhost")
	}
	out, err := cmd.CombinedOutput()
	return strings.TrimRight(string(out), "\n"), err
}

// Repo 是解析后的仓库身份。
type Repo struct {
	CommonDir string // canonical git-common-dir（仓库身份）
	Root      string // 主 worktree 根（common dir 的宿主）
}

func canonical(p string) string {
	if r, err := filepath.EvalSymlinks(p); err == nil {
		p = r
	}
	return filepath.Clean(p)
}

// ResolveRepo 从任意目录解析仓库身份。不能假设 root/.git 是目录
// （linked worktree / submodule 是 gitfile）。
func (s *Service) ResolveRepo(ctx context.Context, dir string) (Repo, error) {
	dir = filepath.Clean(dir)
	if !filepath.IsAbs(dir) {
		return Repo{}, errf("BAD_PATH", "dir must be absolute: %s", dir)
	}
	common, err := git(ctx, dir, "rev-parse", "--git-common-dir")
	if err != nil {
		return Repo{}, errf("NOT_GIT_REPO", "%s", common)
	}
	if !filepath.IsAbs(common) {
		common = filepath.Join(dir, common)
	}
	common = canonical(common)
	// 主 worktree 根：porcelain 列表第一个条目即主 worktree
	out, err := git(ctx, dir, "worktree", "list", "--porcelain")
	if err != nil {
		return Repo{}, errf("GIT_ERROR", "%s", out)
	}
	root := ""
	for _, line := range strings.Split(out, "\n") {
		if p, ok := strings.CutPrefix(line, "worktree "); ok {
			root = canonical(p)
			break
		}
	}
	if root == "" {
		return Repo{}, errf("NOT_GIT_REPO", "no worktree entries under %s", dir)
	}
	return Repo{CommonDir: common, Root: root}, nil
}

// lock 持仓库级 flock；返回解锁函数。
func (s *Service) lock(repo Repo) (func(), error) {
	path := filepath.Join(repo.CommonDir, "roam-worktree.lock")
	f, err := os.OpenFile(path, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return nil, errf("LOCK_FAILED", "%v", err)
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX); err != nil {
		f.Close()
		return nil, errf("LOCK_FAILED", "%v", err)
	}
	return func() { _ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN); f.Close() }, nil
}

func (s *Service) invalidate(repo Repo) {
	s.mu.Lock()
	delete(s.cache, repo.CommonDir)
	s.mu.Unlock()
}

// ── 数据模型 ─────────────────────────────────────────────

type SessRef struct {
	Session string `json:"session"`
	Primary bool   `json:"primary"` // 该会话的 active pane 是否落在此 worktree
	// Dormant 会话被机器重启带走了，但台账还认得它，点开即恢复。
	// 它照样算「这个 worktree 有人用着」——清掉目录，会话就再也恢复不出来了。
	Dormant bool `json:"dormant,omitempty"`
}

type Worktree struct {
	Path      string `json:"path"`
	Branch    string `json:"branch"` // 短名；detached 为空
	Head      string `json:"head"`
	IsMain    bool   `json:"isMain"`
	Base      string `json:"base"` // roam.baseref 短名；"" = unknown
	StartOid  string `json:"startOid,omitempty"`
	CreatedBy string `json:"createdBy,omitempty"`
	CreatedAt string `json:"createdAt,omitempty"`
	External  bool   `json:"external"` // 非 roam 创建（无 roam.* 字段）
	// Adopted = 这个 worktree 是给一条**既有分支**开的（roam.adopted），分支不是我们建的。
	// 收尾时「顺手删分支」对它就是删用户自己的东西：调用方据此把删分支默认关掉。
	Adopted        bool      `json:"adopted,omitempty"`
	Dirty          int       `json:"dirty"` // 未提交改动（含暂存）
	Untracked      int       `json:"untracked"`
	CommittedAhead int       `json:"committedAhead"` // 未合并到 base 的提交（≠ 未推送）
	Behind         int       `json:"behind"`
	LastCommitAt   int64     `json:"lastCommitAt"`
	Locked         bool      `json:"locked"`
	Prunable       bool      `json:"prunable"`
	Sessions       []SessRef `json:"sessions"`
	// 合入检测（10 设计 §4）：对比目标优先 origin/<base>（Sync fetch 来的远端真相），
	// 无远端时退回本地 base——此时语义与旧版一致。
	MergedInto  string `json:"mergedInto,omitempty"`  // 非空 = 已检出合入的目标 ref
	MergedKind  string `json:"mergedKind,omitempty"`  // ancestry(S1) | squash(S2 patch-id 等价)
	RemoteGone  bool   `json:"remoteGone,omitempty"`  // S3：曾推送、远端分支现已删（仅佐证）
	AheadUnique int    `json:"aheadUnique,omitempty"` // git cherry 的 + 数（补丁级真领先）
	// 三态细化（已提交→已推送→已合入）：Pushed = 当前 HEAD 已落在 origin/<branch>，
	// 把旧「待收尾」黄条里的「本地已提交未推送」与「已推送待合入」拆开（本地 ref 判定，无网络）。
	Pushed bool `json:"pushed,omitempty"`
}

// ── Create ───────────────────────────────────────────────

type CreateReq struct {
	Dir    string `json:"dir"`
	Branch string `json:"branch"` // 空 = 旧时间戳行为（兼容）
	Base   string `json:"base"`   // 空 = 仓库默认分支
	Remote string `json:"remote"` // 非空则先 fetch remote base
	// Dirname 指定 .worktrees/ 下的目录名，编排层一律传会话 id。
	// 分支名派生自展示名，中文标题会被 autoBranch 清成空、兜底成字面量 "task"——
	// 于是每个中文任务都叫 task/task-2/task-3，且 task 被收尾释放后原地复用同一路径，
	// 新旧任务的会话归属、标注、开着的终端全指向同一个目录。会话 id 唯一且不回收。
	Dirname string `json:"dirname"`
	// Existing = Branch 指的是一条**已存在的本地分支**：检出它，不新建分支。
	// 「已有」于是不只有 worktree：手上那条还没工作区的分支，也能直接开一个进去接着干。
	Existing bool `json:"existing"`
}

type CreateResp struct {
	Path     string `json:"path"`
	Branch   string `json:"branch"`
	Base     string `json:"base"`
	StartOid string `json:"startOid"`
}

var slugRe = regexp.MustCompile(`[^a-zA-Z0-9._-]+`)

func pathSlug(branch string) string {
	s := slugRe.ReplaceAllString(strings.ReplaceAll(branch, "/", "-"), "-")
	s = strings.Trim(s, "-.")
	if s == "" {
		s = "wt"
	}
	return s
}

// defaultBase 解析缺省 base：origin/HEAD 指向的本地分支 → 本地 main → master →
// 当前 HEAD 分支兜底。很多仓库没设 origin/HEAD（clone 早/本地建库），不能让 base
// 默认成当前检出的 feature 分支——base 应始终是本地主干。
func (s *Service) defaultBase(ctx context.Context, repo Repo) string {
	if out, err := git(ctx, repo.Root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"); err == nil {
		if name := strings.TrimPrefix(strings.TrimSpace(out), "origin/"); branchExists(ctx, repo, name) {
			return name
		}
	}
	for _, name := range []string{"main", "master"} {
		if branchExists(ctx, repo, name) {
			return name
		}
	}

	return ""
}

func (s *Service) Create(ctx context.Context, req CreateReq) (CreateResp, error) {
	return s.create(ctx, req, nil)
}

func (s *Service) create(ctx context.Context, req CreateReq, prepared *PreparedBase) (CreateResp, error) {
	repo, err := s.ResolveRepo(ctx, req.Dir)
	if err != nil {
		return CreateResp{}, err
	}
	if out, e := git(ctx, repo.Root, "rev-parse", "--verify", "HEAD"); e != nil {
		return CreateResp{}, errf("EMPTY_REPO", "repository has no commits yet: %s", out)
	}

	base := strings.TrimSpace(req.Base)
	if base == "" {
		base = s.defaultBase(ctx, repo)
		if base == "" && req.Existing {
			return CreateResp{}, errf("BASE_UNRESOLVED", "cannot determine existing branch base")
		}
	}
	unlock, err := s.lock(repo)
	if err != nil {
		return CreateResp{}, err
	}
	defer unlock()
	defer s.invalidate(repo)
	var startOid string
	var chosen PreparedBase
	if !req.Existing {
		if prepared != nil {
			if prepared.repo != repo.Root || prepared.oid == "" {
				return CreateResp{}, errf("BAD_BASE", "prepared base belongs to another repository")
			}
			chosen = *prepared
		} else {
			chosen, err = s.freshBase(ctx, repo, base, strings.TrimSpace(req.Remote))
			if err != nil {
				return CreateResp{}, err
			}
		}
		startOid, base = chosen.oid, chosen.base
	}

	branch := strings.TrimSpace(req.Branch)
	finalBranch := branch
	if req.Existing {
		// 收养：分支必须已存在、且没被别处检出（git 本就不许一条分支同时检出两次，
		// 先自己查一遍是为了给出「谁占着」而不是一句 git 报错）。校验放锁内，
		// 免得两个请求同时收养同一条分支。
		if branch == "" {
			return CreateResp{}, errf("BAD_BRANCH", "existing branch name required")
		}
		if !branchExists(ctx, repo, branch) {
			return CreateResp{}, errf("BAD_BRANCH", "no such local branch: %s", branch)
		}
		if p := branchWorktree(ctx, repo, branch); p != "" {
			return CreateResp{}, &Err{Code: "BRANCH_CHECKED_OUT", Message: "branch is already checked out at " + p,
				Extra: map[string]any{"branch": branch, "path": p}}
		}
		// 起点记「与 base 的分叉点」而不是分支尖端：面板的 ahead / ownWork 都以
		// StartOid 为基准，记成尖端的话分支上已有的提交会被算成「没干过活」。
		if out, e := git(ctx, repo.Root, "merge-base", base, branch); e == nil {
			startOid = strings.TrimSpace(out)
		}
		if startOid == "" {
			out, e := git(ctx, repo.Root, "rev-parse", "--verify", "--end-of-options", branch+"^{commit}")
			if e != nil {
				return CreateResp{}, errf("BAD_BRANCH", "cannot resolve %s: %s", branch, out)
			}
			startOid = out
		}
	} else {
		legacy := branch == ""
		if legacy {
			now := time.Now()
			branch = "_" + now.Format("20060102150405") + fmt.Sprintf("%03d", now.Nanosecond()/1e6)
		} else {
			if out, e := git(ctx, repo.Root, "check-ref-format", "--branch", branch); e != nil {
				return CreateResp{}, errf("BAD_BRANCH", "invalid branch name %q: %s", branch, out)
			}
		}
		// 锁内分配最终 branch/path（冲突加序号后缀）
		finalBranch = branch
		for i := 2; branchExists(ctx, repo, finalBranch) && i < 100; i++ {
			finalBranch = fmt.Sprintf("%s-%d", branch, i)
		}
		if branchExists(ctx, repo, finalBranch) {
			return CreateResp{}, errf("BRANCH_TAKEN", "cannot allocate branch name from %q", branch)
		}
	}
	wtDir := filepath.Join(repo.Root, ".worktrees")
	if err := os.MkdirAll(wtDir, 0o755); err != nil {
		return CreateResp{}, errf("MKDIR_FAILED", "%v", err)
	}
	slug := pathSlug(finalBranch)
	if d := strings.TrimSpace(req.Dirname); d != "" {
		slug = pathSlug(d)
	}
	path := filepath.Join(wtDir, slug)
	for i := 2; pathExists(path) && i < 100; i++ {
		path = filepath.Join(wtDir, fmt.Sprintf("%s-%d", slug, i))
	}

	add := []string{"worktree", "add", "--no-track", "-b", finalBranch, "--", path, startOid}
	if req.Existing {
		add = []string{"worktree", "add", "--", path, finalBranch} // 检出既有分支，不新建
	}
	if out, e := git(ctx, repo.Root, add...); e != nil {
		return CreateResp{}, errf("WORKTREE_ADD_FAILED", "%s", out)
	}
	// 身份写进 git：worktree-local config（先在 common 配置启用扩展）
	_, _ = git(ctx, repo.Root, "config", "extensions.worktreeConfig", "true")
	ident := map[string]string{
		"roam.baseref":   base,
		"roam.startoid":  startOid,
		"roam.createdby": "roam",
		"roam.createdat": time.Now().Format(time.RFC3339),
	}
	if !req.Existing {
		ident["roam.baseremote"] = chosen.remote
		ident["roam.remote-baseref"] = chosen.remoteBranch
	}
	if req.Existing {
		ident["roam.adopted"] = "1" // 分支不是我们建的：收尾时别顺手删掉它
	}
	for k, v := range ident {
		if out, e := git(ctx, path, "config", "--worktree", k, v); e != nil {
			// 写身份失败视为创建失败：反向补偿，绝不留下无身份的"roam worktree"。
			// 收养来的分支是用户自己的，补偿只拆 worktree，不许删分支。
			_, _ = git(ctx, repo.Root, "worktree", "remove", "--force", "--", path)
			if !req.Existing {
				_, _ = git(ctx, repo.Root, "branch", "-D", "--", finalBranch)
			}
			return CreateResp{}, errf("CONFIG_FAILED", "git config --worktree %s: %s", k, out)
		}
	}
	s.ensureExclude(repo)
	return CreateResp{Path: path, Branch: finalBranch, Base: base, StartOid: startOid}, nil
}

func branchExists(ctx context.Context, repo Repo, name string) bool {
	_, err := git(ctx, repo.Root, "show-ref", "--verify", "--quiet", "refs/heads/"+name)
	return err == nil
}

// branchWorktree 返回检出着该分支的 worktree 路径（含主仓库），没被检出则为空。
func branchWorktree(ctx context.Context, repo Repo, name string) string {
	out, err := git(ctx, repo.Root, "for-each-ref", "--format=%(worktreepath)", "refs/heads/"+name)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(out)
}

func pathExists(p string) bool { _, err := os.Stat(p); return err == nil }

// ensureExclude 幂等追加 /.worktrees/ 到 common git dir 的 info/exclude。
func (s *Service) ensureExclude(repo Repo) {
	const line = "/.worktrees/"
	p := filepath.Join(repo.CommonDir, "info", "exclude")
	b, _ := os.ReadFile(p)
	for _, l := range strings.Split(string(b), "\n") {
		if strings.TrimSpace(l) == line {
			return
		}
	}
	_ = os.MkdirAll(filepath.Dir(p), 0o755)
	f, err := os.OpenFile(p, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o644)
	if err != nil {
		return
	}
	defer f.Close()
	if len(b) > 0 && !strings.HasSuffix(string(b), "\n") {
		_, _ = f.WriteString("\n")
	}
	_, _ = f.WriteString(line + "\n")
}

// ── 合入信号链（10 设计 §4）─────────────────────────────────

// mergeSignal 判定 worktree 是否已并入 target；命中返回 (kind, true)，否则 (_, false)。
// 允许读/标注 w（如 S2 顺手记 AheadUnique）。约定：调用前已确保 ownWork（worktree 真
// 离开分叉点），故各判据只管「HEAD 是否已进 target」，无需再自防空 worktree。
type mergeSignal func(ctx context.Context, w *Worktree, target string) (kind string, merged bool)

// mergeSignals 合入判据链，顺序即优先级——命中即止。横向可扩展：加新判据（如
// note-based、PR 号回填、reflog 溯源…）只需往本表追加一项，List 主流程零改动。
var mergeSignals = []mergeSignal{
	// S1 祖先：merge commit / ff / rebase 后 ff——HEAD 已是 target 的祖先。
	func(ctx context.Context, w *Worktree, target string) (string, bool) {
		if _, e := git(ctx, w.Path, "merge-base", "--is-ancestor", "HEAD", target); e == nil {
			return "ancestry", true
		}
		return "", false
	},
	// S2 补丁等价：squash/逐提交 rebase 后，任务分支提交按 patch-id 全被 target 覆盖
	// （cherry 全 `-`）。出现 `+` 即有真领先，宁可漏判不错判。
	func(ctx context.Context, w *Worktree, target string) (string, bool) {
		if w.CommittedAhead <= 0 {
			return "", false
		}
		out, e := git(ctx, w.Path, "cherry", target, "HEAD")
		if e != nil {
			return "", false
		}
		plus := 0
		for _, l := range strings.Split(out, "\n") {
			if strings.HasPrefix(l, "+ ") {
				plus++
			}
		}
		w.AheadUnique = plus
		return "squash", plus == 0 && strings.TrimSpace(out) != ""
	},
}

// ── List ─────────────────────────────────────────────────

// List 解析 porcelain 清单并补状态；带 3s 缓存。无任何写副作用。
func (s *Service) List(ctx context.Context, dir string) ([]Worktree, error) {
	repo, err := s.ResolveRepo(ctx, dir)
	if err != nil {
		return nil, err
	}
	s.mu.Lock()
	if c, ok := s.cache[repo.CommonDir]; ok && time.Since(c.at) < listCacheTTL {
		s.mu.Unlock()
		return s.joinSessions(ctx, c.data), nil
	}
	s.mu.Unlock()

	out, e := git(ctx, repo.Root, "worktree", "list", "--porcelain")
	if e != nil {
		return nil, errf("GIT_ERROR", "%s", out)
	}
	var list []Worktree
	var cur *Worktree
	flush := func() {
		if cur != nil {
			list = append(list, *cur)
			cur = nil
		}
	}
	for _, line := range strings.Split(out, "\n") {
		switch {
		case strings.HasPrefix(line, "worktree "):
			flush()
			cur = &Worktree{Path: canonical(strings.TrimPrefix(line, "worktree "))}
		case cur == nil:
		case strings.HasPrefix(line, "HEAD "):
			cur.Head = strings.TrimPrefix(line, "HEAD ")
		case strings.HasPrefix(line, "branch "):
			cur.Branch = strings.TrimPrefix(strings.TrimPrefix(line, "branch "), "refs/heads/")
		case line == "locked" || strings.HasPrefix(line, "locked "):
			cur.Locked = true
		case line == "prunable" || strings.HasPrefix(line, "prunable "):
			cur.Prunable = true
		}
	}
	flush()

	s.mu.Lock()
	rs := s.remote[repo.CommonDir]
	s.mu.Unlock()

	// 逐 worktree 的加工彼此独立（各写各的 w，rs 只读），并发跑：blade-agent 一个仓库 25 个
	// worktree、每个八九条 git，串行 1.7s，/projects 整个被它压着。并发上限 4：git 起进程不算重，
	// 但同一仓库的 index / packed-refs 锁会让更高的并发互相等
	var wg sync.WaitGroup
	sem := make(chan struct{}, 4)
	for i := range list {
		w := &list[i]
		w.IsMain = w.Path == repo.Root
		if w.Prunable {
			continue
		}
		wg.Add(1)
		sem <- struct{}{}
		go func(w *Worktree) {
			defer wg.Done()
			defer func() { <-sem }()
			s.enrichWorktree(ctx, w, rs)
		}(w)
	}
	wg.Wait()
	s.mu.Lock()
	s.cache[repo.CommonDir] = listCache{at: time.Now(), data: list}
	s.mu.Unlock()
	return s.joinSessions(ctx, list), nil
}

// ── 远端同步（10 设计 §3）────────────────────────────────

type SyncResult struct {
	SyncedAt int64  `json:"syncedAt"`           // 最近一次成功观测（unix 秒）；0 = 从未成功
	Error    string `json:"error,omitempty"`    // 本次失败原因（判定沿用上次观测）
	NoRemote bool   `json:"noRemote,omitempty"` // 无 origin：纯本地仓库，无需同步
}

const syncTimeout = 10 * time.Second

// Sync 轻量同步远端：一次 ls-remote 观测远端分支集合（S3 branch-gone 的数据源），
// 再 fetch 各 worktree 的合并目标分支（更新 origin/<base>，S1/S2 的对比对象）。
// 失败静默退化：保留上次观测、只记错误，绝不阻塞/弹凭据提示（GIT_TERMINAL_PROMPT=0
// + 硬超时兜底）。无 origin 的纯本地仓库直接短路。
func (s *Service) Sync(ctx context.Context, dir string) (SyncResult, error) {
	repo, err := s.ResolveRepo(ctx, dir)
	if err != nil {
		return SyncResult{}, err
	}
	if _, e := git(ctx, repo.Root, "remote", "get-url", "origin"); e != nil {
		return SyncResult{NoRemote: true}, nil
	}
	nctx, cancel := context.WithTimeout(ctx, syncTimeout)
	defer cancel()

	prev := func() remoteState { s.mu.Lock(); defer s.mu.Unlock(); return s.remote[repo.CommonDir] }()
	fail := func(msg string) SyncResult {
		s.mu.Lock()
		s.remote[repo.CommonDir] = remoteState{at: prev.at, err: msg, heads: prev.heads}
		s.mu.Unlock()
		var at int64
		if !prev.at.IsZero() {
			at = prev.at.Unix()
		}
		return SyncResult{SyncedAt: at, Error: msg}
	}

	out, e := git(nctx, repo.Root, "ls-remote", "--heads", "origin")
	if e != nil {
		return fail(strings.TrimSpace(out)), nil
	}
	heads := map[string]bool{}
	for _, line := range strings.Split(out, "\n") {
		if _, ref, ok := strings.Cut(line, "\t"); ok {
			if name := strings.TrimPrefix(ref, "refs/heads/"); name != ref {
				heads[strings.TrimSpace(name)] = true
			}
		}
	}

	// 合并目标 = 默认主干 ∪ 各 roam worktree 记录的 base（去重，且远端确有该分支）
	bases := map[string]bool{}
	if b := s.defaultBase(nctx, repo); b != "" {
		bases[b] = true
	}
	if list, e := s.List(ctx, dir); e == nil {
		for _, w := range list {
			if !w.IsMain && !w.External && w.Base != "" {
				bases[w.Base] = true
			}
		}
	}
	var refspecs []string
	for b := range bases {
		if heads[b] {
			refspecs = append(refspecs, "+refs/heads/"+b+":refs/remotes/origin/"+b)
		}
	}
	sort.Strings(refspecs)
	if len(refspecs) > 0 {
		if out, e := git(nctx, repo.Root, append([]string{"fetch", "--no-tags", "origin"}, refspecs...)...); e != nil {
			return fail(strings.TrimSpace(out)), nil
		}
	}

	now := time.Now()
	s.mu.Lock()
	s.remote[repo.CommonDir] = remoteState{at: now, heads: heads}
	s.mu.Unlock()
	s.invalidate(repo) // 让下一次 List 立即吃到新 origin/<base>
	return SyncResult{SyncedAt: now.Unix()}, nil
}

// ── session ↔ worktree join（cwd 现算，不写台账）──────────

type pane struct {
	ID      string // tmux #{session_id}（$3）：改名不变、server 内唯一，会话归属的内部键
	Session string
	Active  bool
	Cwd     string
	// Dormant 只有 homePanes 造出来的「归属 pane」会置位：那不是真 pane，
	// 是台账里一个等着被点开恢复的会话。
	Dormant bool
}

func tmuxBin() string {
	if b := os.Getenv("TMUX_BIN"); b != "" {
		return b
	}
	return "tmux"
}

func tmuxPanes(ctx context.Context) []pane {
	cmd := exec.CommandContext(ctx, tmuxBin(), "list-panes", "-a", "-F", "#{session_id}\t#{session_name}\t#{pane_active}\t#{pane_current_path}")
	out, err := cmd.Output()
	if err != nil {
		return nil
	}
	var panes []pane
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.SplitN(line, "\t", 4)
		if len(parts) == 4 {
			panes = append(panes, pane{ID: parts[0], Session: parts[1], Active: parts[2] == "1", Cwd: canonical(parts[3])})
		}
	}
	return panes
}

// underPath 按路径段边界判断 p 是否在 root 内。
func underPath(p, root string) bool {
	return p == root || strings.HasPrefix(p, root+string(filepath.Separator))
}

func (s *Service) joinSessions(ctx context.Context, list []Worktree) []Worktree {
	out := make([]Worktree, len(list))
	copy(out, list)
	// 按会话钉死的 home 目录归属（不是实时 pane cwd）：cd 走了也还挂在原 worktree 下。
	panes := homePanes(s.sessionHomes(ctx))
	for i := range out {
		out[i].Sessions = nil
	}
	for _, p := range panes {
		// 最长前缀命中（worktree 可能嵌套于主仓库之下，主 worktree 也参与）
		best, bestLen := -1, -1
		for i := range out {
			if underPath(p.Cwd, out[i].Path) && len(out[i].Path) > bestLen {
				best, bestLen = i, len(out[i].Path)
			}
		}
		if best < 0 {
			continue
		}
		found := false
		for j := range out[best].Sessions {
			if out[best].Sessions[j].Session == p.Session {
				out[best].Sessions[j].Primary = out[best].Sessions[j].Primary || p.Active
				found = true
			}
		}
		if !found {
			out[best].Sessions = append(out[best].Sessions, SessRef{Session: p.Session, Primary: p.Active, Dormant: p.Dormant})
		}
	}
	return out
}

// ── Annotations（跨仓库：session → worktree 归属）─────────

type Annotation struct {
	SessionID string          `json:"sessionId,omitempty"` // tmux #{session_id}：改名不变的会话身份
	Home      string          `json:"home"`                // 会话钉死的归属目录（非 git 项目按它做前缀归属）
	Primary   *AnnotationHit  `json:"primary,omitempty"`
	Matches   []AnnotationHit `json:"matches"`
	Ambiguous bool            `json:"ambiguous"` // 保留字段：归属已钉死为单一 home，恒 false
	// Dormant 会话只存在于台账里（机器重启带走了 tmux 那一半），点开即恢复。
	// 归属照常算，但它没有 pane、没有进程——绿点/待输入一类的判断都不适用。
	Dormant bool `json:"dormant,omitempty"`
}

type AnnotationHit struct {
	Repo     string `json:"repo"`     // 主仓库根
	Worktree string `json:"worktree"` // worktree 根（linked 才有意义）
	Branch   string `json:"branch"`
	Linked   bool   `json:"linked"`   // 是否 linked worktree（≠ 主 worktree）
	External bool   `json:"external"` // 无 roam.* 身份（用户手建），UI 标 ⧉
}

type cwdInfo struct {
	at  time.Time
	hit *AnnotationHit
}

var (
	cwdCacheMu sync.Mutex
	cwdCache   = map[string]cwdInfo{}
)

func resolveCwd(ctx context.Context, cwd string) *AnnotationHit {
	cwdCacheMu.Lock()
	if c, ok := cwdCache[cwd]; ok && time.Since(c.at) < 5*time.Second {
		cwdCacheMu.Unlock()
		return c.hit
	}
	cwdCacheMu.Unlock()
	var hit *AnnotationHit
	if top, err := git(ctx, cwd, "rev-parse", "--show-toplevel"); err == nil {
		top = canonical(top)
		gitDir, _ := git(ctx, cwd, "rev-parse", "--absolute-git-dir")
		commonDir, _ := git(ctx, cwd, "rev-parse", "--git-common-dir")
		if !filepath.IsAbs(commonDir) {
			commonDir = filepath.Join(cwd, commonDir)
		}
		linked := canonical(gitDir) != canonical(commonDir)
		branch, berr := git(ctx, cwd, "rev-parse", "--abbrev-ref", "HEAD")
		if berr != nil {
			branch = "" // 空仓库 HEAD 未出生：git 的报错文本不是分支名
		}
		repoRoot := top
		if linked {
			// 主仓库根 = common dir 的宿主目录
			repoRoot = filepath.Dir(canonical(commonDir))
		}
		external := false
		if linked {
			cb, cbErr := git(ctx, top, "config", "--worktree", "--get", "roam.createdby")
			external = cbErr != nil || strings.TrimSpace(cb) != "roam"
		}
		hit = &AnnotationHit{Repo: repoRoot, Worktree: top, Branch: strings.TrimSpace(branch), Linked: linked, External: external}
	}
	cwdCacheMu.Lock()
	cwdCache[cwd] = cwdInfo{at: time.Now(), hit: hit}
	cwdCacheMu.Unlock()
	return hit
}

// RepoWorktrees 是 ListAll 的分组单元：一个仓库 + 其全部 worktree。
type RepoWorktrees struct {
	Repo      string     `json:"repo"`
	Worktrees []Worktree `json:"worktrees"`
}

// ListAll 汇总当前全部会话（归属目录）触达的仓库的 worktree 清单——W4 跨仓库总览。
// 仓库集合来自 home join（5s 缓存），逐仓库 List（3s 缓存），单仓库失败跳过不拖累整体。
func (s *Service) ListAll(ctx context.Context) []RepoWorktrees {
	seen := map[string]bool{}
	var repos []string
	for _, p := range homePanes(s.sessionHomes(ctx)) {
		hit := resolveCwd(ctx, p.Cwd)
		if hit == nil || hit.Repo == "" || seen[hit.Repo] {
			continue
		}
		seen[hit.Repo] = true
		repos = append(repos, hit.Repo)
	}
	sort.Strings(repos)
	out := []RepoWorktrees{}
	for _, root := range repos {
		list, err := s.List(ctx, root)
		if err != nil {
			continue
		}
		out = append(out, RepoWorktrees{Repo: root, Worktrees: list})
	}
	return out
}

// SessionCwds 全部会话的**归属目录**快照（canonical，每会话一条）。供非 git 项目
// 按目录前缀归属会话（08：项目不与 git 绑定，git 只是可选能力）。
// 这里刻意不给实时 pane cwd：会话 cd 出去不该换项目（见 sessionhome.go）。
func (s *Service) SessionCwds(ctx context.Context) map[string][]string {
	out := map[string][]string{}
	for _, h := range s.sessionHomes(ctx) {
		out[h.Name] = []string{h.Home}
	}
	return out
}

// Annotations 返回 {session → {home, primary, matches[]}}。
// 归属按会话钉死的 home 目录现算：分支/worktree 状态实时（home 里切分支照样变），
// 但「属于哪个仓库/worktree」不随 pane cwd 漂移。非 git 的 home 也会给出条目
// （只有 home 字段），让非 git 项目也能按前缀认领会话。
// 响应仍以**会话名**为 map key：名字是 UI/CLI 的 handle，内部键 sessionId 随行附上。
func (s *Service) Annotations(ctx context.Context) map[string]*Annotation {
	res := map[string]*Annotation{}
	for _, sh := range s.sessionHomes(ctx) {
		a := &Annotation{SessionID: sh.ID, Home: sh.Home, Dormant: sh.Dormant, Matches: []AnnotationHit{}}
		if hit := resolveCwd(ctx, sh.Home); hit != nil {
			h := *hit
			a.Primary = &h
			a.Matches = append(a.Matches, h)
		}
		res[sh.Name] = a
	}
	return res
}

// ── 活动流（08 P2 活动 tab）───────────────────────────────

type LogEntry struct {
	Oid     string `json:"oid"`
	At      int64  `json:"at"`
	Refs    string `json:"refs,omitempty"` // 装饰引用（分支名等）
	Subject string `json:"subject"`
}

var (
	logCacheMu sync.Mutex
	logCache   = map[string]struct {
		at   time.Time
		data []LogEntry
	}{}
)

// RecentLog 全部分支近 30 天提交（--all 含各 worktree 分支），60s 缓存——
// 活动比 worktree 列表变化慢（08 §5.3）。
func (s *Service) RecentLog(ctx context.Context, dir string) ([]LogEntry, error) {
	repo, err := s.ResolveRepo(ctx, dir)
	if err != nil {
		return nil, err
	}
	logCacheMu.Lock()
	if c, ok := logCache[repo.CommonDir]; ok && time.Since(c.at) < 60*time.Second {
		logCacheMu.Unlock()
		return c.data, nil
	}
	logCacheMu.Unlock()
	out, e := git(ctx, repo.Root, "log", "--all", "--since=30.days",
		"-n", "120", "--format=%h%x09%ct%x09%D%x09%s")
	if e != nil {
		return nil, errf("GIT_ERROR", "%s", out)
	}
	entries := []LogEntry{}
	for _, line := range strings.Split(out, "\n") {
		parts := strings.SplitN(line, "\t", 4)
		if len(parts) != 4 || parts[0] == "" {
			continue
		}
		at, _ := strconv.ParseInt(parts[1], 10, 64)
		entries = append(entries, LogEntry{Oid: parts[0], At: at, Refs: parts[2], Subject: parts[3]})
	}
	logCacheMu.Lock()
	logCache[repo.CommonDir] = struct {
		at   time.Time
		data []LogEntry
	}{time.Now(), entries}
	logCacheMu.Unlock()
	return entries, nil
}

// ── DiffBase ─────────────────────────────────────────────

type FileStat struct {
	Path   string `json:"path"`
	Adds   int    `json:"adds"`
	Dels   int    `json:"dels"`
	Binary bool   `json:"binary"`
}

type DiffPart struct {
	Files []FileStat `json:"files"`
	Adds  int        `json:"adds"`
	Dels  int        `json:"dels"`
}

type DiffResp struct {
	Base        string   `json:"base"`
	MergeBase   string   `json:"mergeBase"`
	Committed   DiffPart `json:"committed"`   // mergeBase..HEAD（已提交差异）
	WorkingTree DiffPart `json:"workingTree"` // 未提交改动（另算，不与上混）
	Untracked   int      `json:"untracked"`
}

func parseNumstat(out string) DiffPart {
	var p DiffPart
	for _, l := range strings.Split(out, "\n") {
		parts := strings.SplitN(l, "\t", 3)
		if len(parts) < 3 {
			continue
		}
		f := FileStat{Path: parts[2]}
		if parts[0] == "-" || parts[1] == "-" {
			f.Binary = true
		} else {
			f.Adds, _ = strconv.Atoi(parts[0])
			f.Dels, _ = strconv.Atoi(parts[1])
		}
		p.Adds += f.Adds
		p.Dels += f.Dels
		p.Files = append(p.Files, f)
	}
	return p
}

func (s *Service) DiffBase(ctx context.Context, path string) (DiffResp, error) {
	path = canonical(path)
	base, e := git(ctx, path, "config", "--worktree", "--get", "roam.baseref")
	if e != nil || strings.TrimSpace(base) == "" {
		return DiffResp{}, errf("BASE_UNKNOWN", "worktree has no recorded base (external worktree?)")
	}
	base = strings.TrimSpace(base)
	mb, e := git(ctx, path, "merge-base", base, "HEAD")
	if e != nil {
		return DiffResp{}, errf("GIT_ERROR", "merge-base: %s", mb)
	}
	mb = strings.TrimSpace(mb)
	resp := DiffResp{Base: base, MergeBase: mb}
	if out, e := git(ctx, path, "diff", "--numstat", mb, "HEAD"); e == nil {
		resp.Committed = parseNumstat(out)
	}
	if out, e := git(ctx, path, "diff", "--numstat", "HEAD"); e == nil {
		resp.WorkingTree = parseNumstat(out)
	}
	if out, e := git(ctx, path, "ls-files", "--others", "--exclude-standard"); e == nil && out != "" {
		resp.Untracked = len(strings.Split(out, "\n"))
	}
	return resp, nil
}

// DiffBaseFile 返回单文件相对 mergeBase 的统一 diff 文本（W3 对比视图点开文件用）。
func (s *Service) DiffBaseFile(ctx context.Context, path, file string) (string, error) {
	path = canonical(path)
	base, e := git(ctx, path, "config", "--worktree", "--get", "roam.baseref")
	if e != nil || strings.TrimSpace(base) == "" {
		return "", errf("BASE_UNKNOWN", "worktree has no recorded base")
	}
	mb, e := git(ctx, path, "merge-base", strings.TrimSpace(base), "HEAD")
	if e != nil {
		return "", errf("GIT_ERROR", "merge-base: %s", mb)
	}
	// 对比到工作区（不带 HEAD）：单文件视图呈现 已提交+未提交 的合并结果，
	// 与前端文件条目的合并口径一致（汇总统计仍分开两组数字）。
	out, e := git(ctx, path, "diff", strings.TrimSpace(mb), "--", file)
	if e != nil {
		return "", errf("GIT_ERROR", "%s", out)
	}
	return out, nil
}

// ── Merge ────────────────────────────────────────────────

type MergeReq struct {
	Path         string `json:"path"`
	Strategy     string `json:"strategy"` // merge | squash | rebase
	ExpectedHead string `json:"expectedHead,omitempty"`
}

type MergeResp struct {
	Strategy  string `json:"strategy"`
	Base      string `json:"base"`
	MergedOid string `json:"mergedOid"`
}

func conflictFiles(ctx context.Context, dir string) []string {
	out, _ := git(ctx, dir, "diff", "--name-only", "--diff-filter=U")
	if strings.TrimSpace(out) == "" {
		return nil
	}
	return strings.Split(out, "\n")
}

func inProgress(ctx context.Context, dir string) string {
	for _, p := range []string{"rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "sequencer"} {
		gp, err := git(ctx, dir, "rev-parse", "--git-path", p)
		if err != nil {
			continue
		}
		if !filepath.IsAbs(gp) {
			gp = filepath.Join(dir, gp)
		}
		if pathExists(gp) {
			return p
		}
	}
	return ""
}

func isClean(ctx context.Context, dir string) bool {
	out, err := git(ctx, dir, "status", "--porcelain=v1")
	return err == nil && strings.TrimSpace(out) == ""
}

// baseSite 找 checkout 了 base 的 worktree；没有则建临时 integration worktree。
// 返回 (执行位路径, 清理函数, error)。
func (s *Service) baseSite(ctx context.Context, repo Repo, base string) (string, func(), error) {
	out, e := git(ctx, repo.Root, "worktree", "list", "--porcelain")
	if e != nil {
		return "", nil, errf("GIT_ERROR", "%s", out)
	}
	cur := ""
	for _, line := range strings.Split(out, "\n") {
		if p, ok := strings.CutPrefix(line, "worktree "); ok {
			cur = canonical(p)
		}
		if strings.TrimPrefix(line, "branch ") == "refs/heads/"+base && cur != "" {
			return cur, func() {}, nil
		}
	}
	// 临时 integration worktree（base 未被任何 worktree checkout 时才可能成功）
	tmp := filepath.Join(repo.Root, ".worktrees", fmt.Sprintf("_integr-%d", time.Now().UnixNano()))
	if out, e := git(ctx, repo.Root, "worktree", "add", "--", tmp, base); e != nil {
		return "", nil, errf("BASE_WORKTREE_NOT_FOUND", "base %q is not checked out anywhere and temp worktree failed: %s", base, out)
	}
	cleanup := func() {
		_, _ = git(ctx, repo.Root, "worktree", "remove", "--force", "--", tmp)
	}
	return tmp, cleanup, nil
}

func (s *Service) Merge(ctx context.Context, req MergeReq) (MergeResp, error) {
	path := canonical(req.Path)
	repo, err := s.ResolveRepo(ctx, path)
	if err != nil {
		return MergeResp{}, err
	}
	base, e := git(ctx, path, "config", "--worktree", "--get", "roam.baseref")
	if e != nil || strings.TrimSpace(base) == "" {
		return MergeResp{}, errf("BASE_UNKNOWN", "refusing to merge a worktree without recorded base")
	}
	base = strings.TrimSpace(base)
	srcBranch, e := git(ctx, path, "rev-parse", "--abbrev-ref", "HEAD")
	if e != nil || srcBranch == "HEAD" {
		return MergeResp{}, errf("DETACHED_HEAD", "source worktree is not on a branch")
	}

	unlock, err := s.lock(repo)
	if err != nil {
		return MergeResp{}, err
	}
	defer unlock()
	defer s.invalidate(repo)

	// 确认后漂移防护
	head, _ := git(ctx, path, "rev-parse", "HEAD")
	if req.ExpectedHead != "" && !strings.HasPrefix(head, req.ExpectedHead) {
		return MergeResp{}, errf("HEAD_MOVED", "worktree HEAD changed since confirmation (expected %s, got %s)", req.ExpectedHead, head)
	}
	if p := inProgress(ctx, path); p != "" {
		return MergeResp{}, errf("OPERATION_IN_PROGRESS", "source worktree has %s in progress", p)
	}

	site, cleanup, err := s.baseSite(ctx, repo, base)
	if err != nil {
		return MergeResp{}, err
	}
	defer cleanup()
	if p := inProgress(ctx, site); p != "" {
		return MergeResp{}, errf("OPERATION_IN_PROGRESS", "base worktree has %s in progress", p)
	}
	if !isClean(ctx, site) {
		return MergeResp{}, errf("BASE_DIRTY", "worktree holding %q has uncommitted changes; commit or stash there first", base)
	}

	conflictErr := func(stage, dir, out string) error {
		files := conflictFiles(ctx, dir)
		return &Err{Code: "MERGE_CONFLICT", Message: strings.TrimSpace(out), Extra: map[string]any{
			"stage": stage, "strategy": req.Strategy, "conflictFiles": files, "recovered": true,
		}}
	}

	switch req.Strategy {
	case "merge":
		if out, e := gitID(ctx, site, "merge", "--no-edit", "--", srcBranch); e != nil {
			err := conflictErr("merge", site, out)
			_, _ = git(ctx, site, "merge", "--abort")
			return MergeResp{}, err
		}
	case "squash":
		if out, e := git(ctx, site, "merge", "--squash", "--", srcBranch); e != nil {
			err := conflictErr("merge", site, out)
			if _, e2 := git(ctx, site, "merge", "--abort"); e2 != nil {
				_, _ = git(ctx, site, "reset", "--merge")
			}
			return MergeResp{}, err
		}
		if out, e := gitID(ctx, site, "commit", "--no-verify", "-m", fmt.Sprintf("squash: merge %s into %s (roam)", srcBranch, base)); e != nil {
			_, _ = git(ctx, site, "reset", "--merge")
			return MergeResp{}, errf("COMMIT_FAILED", "%s", out)
		}
	case "rebase":
		// 第一步：在 source worktree 把 source rebase onto base
		if out, e := gitID(ctx, path, "rebase", "--", base); e != nil {
			err := conflictErr("rebase", path, out)
			_, _ = git(ctx, path, "rebase", "--abort")
			return MergeResp{}, err
		}
		// 第二步：base 快进到 source
		if out, e := git(ctx, site, "merge", "--ff-only", "--", srcBranch); e != nil {
			return MergeResp{}, errf("FF_FAILED", "base cannot fast-forward after rebase: %s", out)
		}
	default:
		return MergeResp{}, errf("BAD_STRATEGY", "unknown strategy %q (merge|squash|rebase)", req.Strategy)
	}
	merged, _ := git(ctx, site, "rev-parse", "HEAD")
	return MergeResp{Strategy: req.Strategy, Base: base, MergedOid: strings.TrimSpace(merged)}, nil
}

// ── Remove / Prune ───────────────────────────────────────

type RemoveReq struct {
	Path              string `json:"path"`
	ForceWorktree     bool   `json:"forceWorktree"`     // 脏也删
	DeleteBranch      bool   `json:"deleteBranch"`      // git branch -d
	ForceDeleteBranch bool   `json:"forceDeleteBranch"` // git branch -D（未合并也删）
	IgnoreSessions    bool   `json:"-"`                 // 组合编排内部用（已先杀会话）
}

func (s *Service) Remove(ctx context.Context, req RemoveReq) error {
	path := canonical(req.Path)
	repo, err := s.ResolveRepo(ctx, path)
	if err != nil {
		// 半删残缺态（10 §7 实测）：上次删除半路失败后 gitfile 已没，从 path 解析
		// 仓库必败。改从父目录解析，且必须仍在注册表里（worktree list 可见），
		// 才允许继续走删除（后面的 git remove 失败会落入 RemoveAll 兜底）。
		repo2, e2 := s.ResolveRepo(ctx, filepath.Dir(path))
		if e2 != nil || !s.isRegisteredWorktree(ctx, repo2, path) {
			return err
		}
		repo = repo2
	}
	if path == repo.Root {
		return errf("MAIN_WORKTREE", "refusing to remove the main worktree")
	}
	unlock, err := s.lock(repo)
	if err != nil {
		return err
	}
	defer unlock()
	defer s.invalidate(repo)

	// 占用检查：还有 session/pane 在里面默认禁止删
	if !req.IgnoreSessions {
		var inside []string
		for _, p := range tmuxPanes(ctx) {
			if underPath(p.Cwd, path) {
				inside = append(inside, p.Session)
			}
		}
		if len(inside) > 0 {
			return &Err{Code: "SESSIONS_INSIDE", Message: "sessions are still using this worktree", Extra: map[string]any{"sessions": dedup(inside)}}
		}
	}
	branch, _ := git(ctx, path, "rev-parse", "--abbrev-ref", "HEAD")
	if !req.ForceWorktree {
		st, _ := git(ctx, path, "status", "--porcelain=v1")
		if strings.TrimSpace(st) != "" {
			dirty, untracked := 0, 0
			for _, l := range strings.Split(st, "\n") {
				if strings.HasPrefix(l, "??") {
					untracked++
				} else if strings.TrimSpace(l) != "" {
					dirty++
				}
			}
			return &Err{Code: "WORKTREE_DIRTY", Message: "worktree has uncommitted changes", Extra: map[string]any{"dirty": dirty, "untracked": untracked}}
		}
	}
	args := []string{"worktree", "remove"}
	if req.ForceWorktree {
		args = append(args, "--force")
	}
	args = append(args, "--", path)
	if out, e := git(ctx, repo.Root, args...); e != nil {
		// 兜底（10 §7 实测）：git 删工作树半路失败（如删除中有并发写入 →
		// Directory not empty）会留下「gitfile 已删、注册表还在」的卡死残缺态，
		// 重试连 status 都跑不了。仅当调用方明示 force（破坏性意图明确）且 path
		// 确为本仓库注册的 linked worktree 时，直接 RemoveAll + prune 收干净。
		if !req.ForceWorktree || !s.isRegisteredWorktree(ctx, repo, path) {
			return errf("WORKTREE_REMOVE_FAILED", "%s", out)
		}
		if rmErr := os.RemoveAll(path); rmErr != nil {
			return errf("WORKTREE_REMOVE_FAILED", "%s; fallback rm: %v", out, rmErr)
		}
		_, _ = git(ctx, repo.Root, "worktree", "prune", "--expire", "now")
	}
	if (req.DeleteBranch || req.ForceDeleteBranch) && branch != "" && branch != "HEAD" {
		flag := "-d"
		if req.ForceDeleteBranch {
			flag = "-D"
		}
		if out, e := git(ctx, repo.Root, "branch", flag, "--", branch); e != nil {
			return &Err{Code: "BRANCH_NOT_MERGED", Message: strings.TrimSpace(out), Extra: map[string]any{"branch": branch, "worktreeRemoved": true}}
		}
	}
	return nil
}

// isRegisteredWorktree 校验 path 是本仓库注册的 linked worktree（含半删残缺态——
// gitfile 没了注册表还在时 worktree list 依然列出）。RemoveAll 兜底前的安全闸。
func (s *Service) isRegisteredWorktree(ctx context.Context, repo Repo, path string) bool {
	out, err := git(ctx, repo.Root, "worktree", "list", "--porcelain")
	if err != nil {
		return false
	}
	for _, line := range strings.Split(out, "\n") {
		if p, ok := strings.CutPrefix(line, "worktree "); ok {
			if c := canonical(p); c == path && c != repo.Root {
				return true
			}
		}
	}
	return false
}

func (s *Service) Prune(ctx context.Context, dir string) error {
	repo, err := s.ResolveRepo(ctx, dir)
	if err != nil {
		return err
	}
	unlock, err := s.lock(repo)
	if err != nil {
		return err
	}
	defer unlock()
	defer s.invalidate(repo)
	if out, e := git(ctx, repo.Root, "worktree", "prune"); e != nil {
		return errf("PRUNE_FAILED", "%s", out)
	}
	return nil
}

// CommitAll 把 worktree 里全部改动（含未跟踪）提交为一笔；无改动时为 no-op。
// 供 close-with-worktree 的「合并并删除」先落一笔 wip 用。
func (s *Service) CommitAll(ctx context.Context, path, msg string) error {
	path = canonical(path)
	if isClean(ctx, path) {
		return nil
	}
	if out, e := git(ctx, path, "add", "-A"); e != nil {
		return errf("GIT_ERROR", "add -A: %s", out)
	}
	if out, e := gitID(ctx, path, "commit", "--no-verify", "-m", msg); e != nil {
		return errf("COMMIT_FAILED", "%s", out)
	}
	return nil
}

// Head 返回 worktree 当前 HEAD OID（编排层做确认后漂移校验用，如 crown 冻结）。
func (s *Service) Head(ctx context.Context, path string) (string, error) {
	out, e := git(ctx, canonical(path), "rev-parse", "--verify", "HEAD")
	if e != nil {
		return "", errf("GIT_ERROR", "rev-parse HEAD: %s", out)
	}
	return strings.TrimSpace(out), nil
}

// RemoteBranch 远端分支（结构化拆开 remote 与分支名：分支名可含 /，
// 前端按 "remote/name" 字符串猜切分会错，真相源在这里拆好）。
type RemoteBranch struct {
	Remote string `json:"remote"`
	Name   string `json:"name"`
}

// LocalBranch 是本地分支及其挑选时要看的两件事：最近一次提交多久以前、
// 有没有被某个 worktree（含主仓库）占着——占着的分支收养不了，git 不许同时检出两次。
type LocalBranch struct {
	Name         string `json:"name"`
	LastCommitAt int64  `json:"at,omitempty"`
	Worktree     string `json:"worktree,omitempty"`
}

// Branches 返回本地分支列表、默认 base 与已知远端分支（W1 start-from 选择器用）。
// 远端分支来自本地已有的 remote-tracking ref（不主动 fetch——Create 选定后会 fetch 锁 OID）。
func (s *Service) Branches(ctx context.Context, dir string) ([]LocalBranch, string, []RemoteBranch, error) {
	repo, err := s.ResolveRepo(ctx, dir)
	if err != nil {
		return nil, "", nil, err
	}
	out, e := git(ctx, repo.Root, "for-each-ref", "refs/heads",
		"--format=%(refname:short)%00%(committerdate:unix)%00%(worktreepath)", "--sort=-committerdate")
	if e != nil {
		return nil, "", nil, errf("GIT_ERROR", "%s", out)
	}
	var branches []LocalBranch
	for _, l := range strings.Split(out, "\n") {
		f := strings.Split(strings.TrimSpace(l), "\x00")
		if len(f) == 0 || f[0] == "" {
			continue
		}
		b := LocalBranch{Name: f[0]}
		if len(f) > 1 {
			at, _ := strconv.ParseInt(f[1], 10, 64)
			b.LastCommitAt = at
		}
		if len(f) > 2 && f[2] != "" {
			b.Worktree = canonical(f[2]) // 和 List 的 Path 同口径（软链接解开），前端才对得上
		}
		branches = append(branches, b)
	}
	return branches, s.defaultBase(ctx, repo), s.remoteBranches(ctx, repo), nil
}

// remoteBranches 列 refs/remotes 下的远端分支，按 remote 名精确切前缀
// （remote 名取自 git remote，最长匹配——分支名可含 /）；跳过 HEAD 符号引用。
func (s *Service) remoteBranches(ctx context.Context, repo Repo) []RemoteBranch {
	remOut, e := git(ctx, repo.Root, "remote")
	if e != nil {
		return nil
	}
	var remotes []string
	for _, l := range strings.Split(remOut, "\n") {
		if r := strings.TrimSpace(l); r != "" {
			remotes = append(remotes, r)
		}
	}
	if len(remotes) == 0 {
		return nil
	}
	// 全名 %(refname) 自己剥前缀：%(refname:short) 在歧义时（如本地分支恰叫
	// origin/foo）会输出 remotes/origin/foo，按 remote 前缀匹配失败被静默漏掉。
	out, e := git(ctx, repo.Root, "for-each-ref", "refs/remotes", "--format=%(refname)", "--sort=-committerdate")
	if e != nil {
		return nil
	}
	var list []RemoteBranch
	for _, l := range strings.Split(out, "\n") {
		short := strings.TrimPrefix(strings.TrimSpace(l), "refs/remotes/")
		if short == "" || short == strings.TrimSpace(l) {
			continue
		}
		match := ""
		for _, r := range remotes {
			if strings.HasPrefix(short, r+"/") && len(r) > len(match) {
				match = r
			}
		}
		if match == "" {
			continue
		}
		name := short[len(match)+1:]
		if name == "" || name == "HEAD" {
			continue
		}
		list = append(list, RemoteBranch{Remote: match, Name: name})
	}
	return list
}

func dedup(in []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, s := range in {
		if !seen[s] {
			seen[s] = true
			out = append(out, s)
		}
	}
	return out
}

// enrichWorktree 给一条 worktree 补状态：身份、脏改动、相对 base 的领先/落后、合入判定、已推送、最近提交。
// 只写自己这一条 w；rs 是本轮的远端观测（只读）。List 里并发调用。
func (s *Service) enrichWorktree(ctx context.Context, w *Worktree, rs remoteState) {
	// 身份（roam.* worktree config；读不到 = 外部创建 base unknown）。一条 --get-regexp 读全部：
	// 原来 5 条 --get，25 个 worktree 的仓库光这一项就是 125 次 git 起进程
	if out, e := git(ctx, w.Path, "config", "--worktree", "--get-regexp", `^roam\.`); e == nil {
		for _, l := range strings.Split(out, "\n") {
			k, v, _ := strings.Cut(strings.TrimSpace(l), " ")
			switch k {
			case "roam.baseref":
				w.Base = v
			case "roam.startoid":
				w.StartOid = v
			case "roam.createdby":
				w.CreatedBy = v
			case "roam.createdat":
				w.CreatedAt = v
			case "roam.adopted":
				w.Adopted = v == "1"
			}
		}
	}
	w.External = w.CreatedBy != "roam"
	// 状态
	if st, e := git(ctx, w.Path, "status", "--porcelain=v1"); e == nil && st != "" {
		for _, l := range strings.Split(st, "\n") {
			if strings.HasPrefix(l, "??") {
				w.Untracked++
			} else if strings.TrimSpace(l) != "" {
				w.Dirty++
			}
		}
	}
	if w.Base != "" && !w.IsMain {
		// 对比目标优先远端主干（Sync fetch 更新的 origin/<base>）：远端 PR 合并后
		// 本地 base 没 pull 也能翻绿；无远端跟踪 ref 时退回本地 base（旧行为）。
		target := w.Base
		if _, e := git(ctx, w.Path, "rev-parse", "--verify", "-q", "refs/remotes/origin/"+w.Base); e == nil {
			target = "origin/" + w.Base
		}
		if cnt, e := git(ctx, w.Path, "rev-list", "--left-right", "--count", target+"...HEAD"); e == nil {
			parts := strings.Fields(cnt)
			if len(parts) == 2 {
				w.Behind, _ = strconv.Atoi(parts[0])
				w.CommittedAhead, _ = strconv.Atoi(parts[1])
			}
		}
		// 合入判定：横向可扩展的信号链（mergeSignals），命中即定 kind、靠前优先。
		// 统一前置 ownWork——worktree 必须真离开建时分叉点(StartOid)才算干过活；否则
		// 新开的空 worktree HEAD==分叉点，天然是 target 的祖先，S1 会把它秒判「已合入」。
		// StartOid 建时锁定、不随本地 base 分支移动/删除而失真，比对本地 base ref 更稳；
		// 老 worktree 无 StartOid 时退回「相对 target 有领先提交」兜底（空 worktree=0 不判）。
		ownWork := w.Head != w.StartOid
		if w.StartOid == "" {
			ownWork = w.CommittedAhead > 0
		}
		if ownWork {
			for _, sig := range mergeSignals {
				if kind, ok := sig(ctx, w, target); ok {
					w.MergedInto, w.MergedKind = target, kind
					break
				}
			}
		}
		// S3 branch-gone（仅佐证）：曾有远端跟踪 ref，而最近一次 ls-remote 观测里
		// 远端分支已不在。观测缺失（nil）时静默退化，不报 gone。
		if w.Branch != "" && rs.heads != nil && !rs.heads[w.Branch] {
			if _, e := git(ctx, w.Path, "rev-parse", "--verify", "-q", "refs/remotes/origin/"+w.Branch); e == nil {
				w.RemoteGone = true
			}
		}
		// 已推送：当前 HEAD 已是 origin/<branch> 的祖先（含相等）=提交都已在远端。
		// 纯本地跟踪 ref 判定（Sync fetch 会刷新它），ref 不存在时 merge-base 报错→false。
		if w.Branch != "" {
			if _, e := git(ctx, w.Path, "merge-base", "--is-ancestor", "HEAD", "refs/remotes/origin/"+w.Branch); e == nil {
				w.Pushed = true
			}
		}
	}
	if ts, e := git(ctx, w.Path, "log", "-1", "--format=%ct"); e == nil {
		w.LastCommitAt, _ = strconv.ParseInt(strings.TrimSpace(ts), 10, 64)
	}
}
