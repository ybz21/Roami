// Git 服务：供终端会话右侧「Git 面板」查看当前工作目录所属仓库的分支 / 改动 / 差异 / 最近提交。
// 与文件侧栏一致——整个 Web 控制台已是口令鉴权且提供终端全访问，这里只读 git 状态，不额外限制。
package api

import (
	"context"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// runGit 在 dir 下执行 git；core.quotepath=false 让非 ASCII 路径原样返回（不转义码）。
// GIT_TERMINAL_PROMPT=0：push/pull 需要凭据时直接报错而非挂起等待输入。
// 继承来的 GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE 一律剔掉：我们永远靠 -C 指定仓库，
// 若进程是从 git 钩子一类环境里起来的，这些变量会让 git 认错仓库甚至直接报错。
func runGit(ctx context.Context, dir string, args ...string) (string, error) {
	full := append([]string{"-C", dir, "-c", "core.quotepath=false"}, args...)
	cmd := exec.CommandContext(ctx, "git", full...)
	env := make([]string, 0, len(os.Environ())+1)
	for _, kv := range os.Environ() {
		switch {
		case strings.HasPrefix(kv, "GIT_DIR="),
			strings.HasPrefix(kv, "GIT_WORK_TREE="),
			strings.HasPrefix(kv, "GIT_INDEX_FILE="):
			continue
		}
		env = append(env, kv)
	}
	cmd.Env = append(env, "GIT_TERMINAL_PROMPT=0")
	out, err := cmd.CombinedOutput()
	return string(out), err
}

// gitWriteRoot 校验写操作请求里的 root（必须是绝对路径）。
func gitWriteRoot(c *gin.Context, root string) (string, bool) {
	root = filepath.Clean(root)
	if root == "" || !filepath.IsAbs(root) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return "", false
	}
	return root, true
}

// gitFail 把 git 命令的输出当作错误信息回传，前端直接展示（如 push 鉴权失败）。
func gitFail(c *gin.Context, code, out string, err error) {
	msg := strings.TrimSpace(out)
	if msg == "" {
		msg = err.Error()
	}
	c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": code, "message": msg}})
}

type gitFile struct {
	Path      string `json:"path"`
	Orig      string `json:"orig,omitempty"` // 重命名来源
	Index     string `json:"index"`          // X：暂存区状态
	Work      string `json:"work"`           // Y：工作区状态
	Staged    bool   `json:"staged"`
	Untracked bool   `json:"untracked"`
}

type gitCommit struct {
	Hash    string `json:"hash"`
	Short   string `json:"short"`
	Subject string `json:"subject"`
	Author  string `json:"author"`
	When    string `json:"when"`
}

var (
	aheadRe  = regexp.MustCompile(`ahead (\d+)`)
	behindRe = regexp.MustCompile(`behind (\d+)`)
)

// gitUnquote 还原 porcelain 在含特殊字符时给路径加的双引号。
func gitUnquote(s string) string {
	if len(s) >= 2 && s[0] == '"' && s[len(s)-1] == '"' {
		if u, err := strconv.Unquote(s); err == nil {
			return u
		}
	}
	return s
}

// GitStatus GET /git/status?dir=<path> —— 解析 dir 所属仓库的分支、改动文件、最近提交。
func (a *API) GitStatus(c *gin.Context) {
	dir := filepath.Clean(c.Query("dir"))
	if dir == "" || !filepath.IsAbs(dir) {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 12*time.Second)
	defer cancel()

	root, err := runGit(ctx, dir, "rev-parse", "--show-toplevel")
	if err != nil { // 非 git 仓库 / git 不可用
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"repo": false}})
		return
	}
	root = strings.TrimSpace(root)

	out, err := runGit(ctx, root, "status", "--porcelain=v1", "--branch")
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"repo": false}})
		return
	}

	branch, ahead, behind := "", 0, 0
	files := []gitFile{}
	for _, line := range strings.Split(out, "\n") {
		if line == "" {
			continue
		}
		if strings.HasPrefix(line, "## ") {
			h := line[3:]
			switch {
			case strings.HasPrefix(h, "No commits yet on "):
				branch = strings.TrimSpace(strings.TrimPrefix(h, "No commits yet on "))
			case strings.Contains(h, "..."):
				branch = strings.TrimSpace(h[:strings.Index(h, "...")])
			default:
				branch = strings.TrimSpace(strings.SplitN(h, " ", 2)[0])
			}
			if m := aheadRe.FindStringSubmatch(h); m != nil {
				ahead, _ = strconv.Atoi(m[1])
			}
			if m := behindRe.FindStringSubmatch(h); m != nil {
				behind, _ = strconv.Atoi(m[1])
			}
			continue
		}
		if len(line) < 4 {
			continue
		}
		x, y, rest := string(line[0]), string(line[1]), line[3:]
		gf := gitFile{Index: x, Work: y, Staged: x != " " && x != "?", Untracked: x == "?" && y == "?"}
		if i := strings.Index(rest, " -> "); i >= 0 { // 重命名：old -> new
			gf.Orig = gitUnquote(rest[:i])
			gf.Path = gitUnquote(rest[i+4:])
		} else {
			gf.Path = gitUnquote(rest)
		}
		files = append(files, gf)
	}

	commits := []gitCommit{}
	if logOut, err := runGit(ctx, root, "log", "-n", "20", "--pretty=format:%H%x1f%h%x1f%s%x1f%an%x1f%ar"); err == nil {
		for _, line := range strings.Split(logOut, "\n") {
			if p := strings.Split(line, "\x1f"); len(p) >= 5 {
				commits = append(commits, gitCommit{Hash: p[0], Short: p[1], Subject: p[2], Author: p[3], When: p[4]})
			}
		}
	}

	upstream := strings.TrimSpace(mustGit(ctx, root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"))
	if strings.Contains(upstream, "fatal") {
		upstream = ""
	}
	state := gitRepoState(ctx, root)
	conflicts := []string{}
	if state != "" {
		conflicts = gitConflictFiles(ctx, root)
	}

	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"repo": true, "root": root, "branch": branch, "ahead": ahead, "behind": behind,
		"upstream": upstream, "state": state, "conflicts": conflicts,
		"files": files, "commits": commits,
	}})
}

// GitDiff GET /git/diff?root=<repo>&file=<rel>&staged=<0|1>&untracked=<0|1>&rev=<hash> —— 单文件差异文本。
// 带 rev 时看的是「该提交相对第一父」的差异（提交树里点文件走这条）。
func (a *API) GitDiff(c *gin.Context) {
	root := filepath.Clean(c.Query("root"))
	file := c.Query("file")
	if root == "" || !filepath.IsAbs(root) || file == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_PATH"}})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 12*time.Second)
	defer cancel()

	var out string
	switch {
	case safeRev(c.Query("rev")):
		out, _ = runGit(ctx, root, "show", "--format=", "-m", "--first-parent", c.Query("rev"), "--", file)
	case c.Query("untracked") == "1":
		// 未跟踪文件：与空文件比对得到「全新增」差异（有差异时 git 退出码 1，输出仍有效，忽略 err）。
		out, _ = runGit(ctx, root, "diff", "--no-index", "--", "/dev/null", filepath.Join(root, file))
	case c.Query("staged") == "1":
		out, _ = runGit(ctx, root, "diff", "--cached", "--", file)
	default:
		out, _ = runGit(ctx, root, "diff", "--", file)
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"file": file, "diff": out}})
}

// GitStage POST /git/stage {root, files?:[], all?:bool} —— 暂存改动（git add）。
func (a *API) GitStage(c *gin.Context) {
	var req struct {
		Root  string   `json:"root"`
		Files []string `json:"files"`
		All   bool     `json:"all"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	root, ok := gitWriteRoot(c, req.Root)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	args := []string{"add", "-A"}
	if !req.All {
		if len(req.Files) == 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NO_FILES"}})
			return
		}
		args = append([]string{"add", "--"}, req.Files...)
	}
	if out, err := runGit(ctx, root, args...); err != nil {
		gitFail(c, "GIT_STAGE_FAILED", out, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// GitUnstage POST /git/unstage {root, files?:[], all?:bool} —— 取消暂存（git reset HEAD）。
func (a *API) GitUnstage(c *gin.Context) {
	var req struct {
		Root  string   `json:"root"`
		Files []string `json:"files"`
		All   bool     `json:"all"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	root, ok := gitWriteRoot(c, req.Root)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	args := []string{"reset", "-q", "HEAD"}
	if !req.All {
		if len(req.Files) == 0 {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "NO_FILES"}})
			return
		}
		args = append([]string{"reset", "-q", "HEAD", "--"}, req.Files...)
	}
	if out, err := runGit(ctx, root, args...); err != nil {
		gitFail(c, "GIT_UNSTAGE_FAILED", out, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// GitDiscard POST /git/discard {root, files?:[], untracked?:[]} —— 放弃工作区改动。
// files：已跟踪文件 → git checkout 恢复；untracked：未跟踪文件 → 直接删除（限 root 内）。
func (a *API) GitDiscard(c *gin.Context) {
	var req struct {
		Root      string   `json:"root"`
		Files     []string `json:"files"`
		Untracked []string `json:"untracked"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	root, ok := gitWriteRoot(c, req.Root)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	if len(req.Files) > 0 {
		if out, err := runGit(ctx, root, append([]string{"checkout", "--"}, req.Files...)...); err != nil {
			gitFail(c, "GIT_DISCARD_FAILED", out, err)
			return
		}
	}
	for _, f := range req.Untracked {
		p := filepath.Clean(filepath.Join(root, f))
		if p == root || !strings.HasPrefix(p, root+string(os.PathSeparator)) { // 防穿越到 root 外
			continue
		}
		os.RemoveAll(p)
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true}})
}

// GitCommit POST /git/commit {root, message, push?:bool} —— 提交已暂存改动，可选随后 push。
func (a *API) GitCommit(c *gin.Context) {
	var req struct {
		Root    string `json:"root"`
		Message string `json:"message"`
		Push    bool   `json:"push"`
		Amend   bool   `json:"amend"` // 修订上次提交（重写 HEAD）
		All     bool   `json:"all"`   // -a：提交前自动暂存已跟踪文件的改动
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	root, ok := gitWriteRoot(c, req.Root)
	if !ok {
		return
	}
	if strings.TrimSpace(req.Message) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "EMPTY_MESSAGE"}})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 30*time.Second)
	defer cancel()
	cargs := []string{"commit"}
	if req.Amend {
		cargs = append(cargs, "--amend")
	}
	if req.All {
		cargs = append(cargs, "-a")
	}
	out, err := runGit(ctx, root, append(cargs, "-m", req.Message)...)
	if err != nil {
		gitFail(c, "GIT_COMMIT_FAILED", out, err)
		return
	}
	result := out
	if req.Push {
		pctx, pcancel := context.WithTimeout(c.Request.Context(), 120*time.Second)
		defer pcancel()
		pout, perr := runGit(pctx, root, "push")
		result += "\n" + pout
		if perr != nil {
			gitFail(c, "GIT_PUSH_FAILED", result, perr)
			return
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true, "output": strings.TrimSpace(result)}})
}

// GitIsRepo GET /git/is-repo?path=<dir> —— 检查目录是否为 git 仓库。
func (a *API) GitIsRepo(c *gin.Context) {
	dir := filepath.Clean(c.Query("path"))
	if dir == "" || !filepath.IsAbs(dir) {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"repo": false}})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	state, err := a.WT.RepositoryState(ctx, dir)
	if err != nil {
		wtErr(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": state})
}

func (a *API) GitInitialize(c *gin.Context) {
	var b struct {
		Dir string `json:"dir"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || strings.TrimSpace(b.Dir) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	ctx, cancel := wtCtx(c)
	defer cancel()
	state, err := a.WT.InitializeRepository(ctx, b.Dir)
	if err != nil {
		wtErr(c, err)
		return
	}
	projRespMu.Lock()
	projResp = nil
	projRespMu.Unlock()
	c.JSON(http.StatusOK, gin.H{"data": state})
}

// GitOp POST /git/op {root, op} —— 远端操作：push / pull / fetch / sync(pull+push)。
func (a *API) GitOp(c *gin.Context) {
	var req struct {
		Root string `json:"root"`
		Op   string `json:"op"`
	}
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_FORM", "message": err.Error()}})
		return
	}
	root, ok := gitWriteRoot(c, req.Root)
	if !ok {
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 120*time.Second)
	defer cancel()
	var out string
	var err error
	switch req.Op {
	case "push":
		out, err = runGit(ctx, root, "push")
	case "fetch":
		out, err = runGit(ctx, root, "fetch", "--prune")
	case "pull":
		out, err = runGit(ctx, root, "pull")
	case "sync": // 先 pull 再 push
		out, err = runGit(ctx, root, "pull")
		if err == nil {
			var pout string
			pout, err = runGit(ctx, root, "push")
			out = strings.TrimSpace(out) + "\n" + pout
		}
	default:
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_OP"}})
		return
	}
	if err != nil {
		gitFail(c, "GIT_OP_FAILED", out, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"ok": true, "output": strings.TrimSpace(out)}})
}
