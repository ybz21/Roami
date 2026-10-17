// 全局搜索（⌘K）的 HTTP 层。
//
//	GET /search?q=&kinds=&limit=&dir=   项目 / 会话 / 项目文件 / 插件 / 蜂群（名字模糊匹配）
//	GET /search/content?q=&dir=&limit=  文件内容（rg，没有则退回 grep）
//
// 这里只做「装配数据源 → 交给引擎 → 出 JSON」。打分、排序、截断在 github.com/ybz21/Roami/backend/search；
// 各数据源在 search_sources.go——**要让一类新东西可搜，改那个文件就够了**。
package api

import (
	"bufio"
	"context"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/search"
)

const maxContentHits = 60

// Search GET /search?q=<查询>[&kinds=project,session,file,plugin,swarm][&limit=N][&dir=<额外根目录>]
func (a *API) Search(c *gin.Context) {
	started := time.Now()
	q := strings.TrimSpace(c.Query("q"))
	if q == "" {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"hits": []search.Hit{}, "truncated": false, "tookMs": 0}})
		return
	}
	limit := clampInt(c.Query("limit"), 40, 1, 200)
	ctx, cancel := context.WithTimeout(c.Request.Context(), 10*time.Second)
	defer cancel()

	dir := strings.TrimSpace(c.Query("dir"))
	roots := a.projectRoots(dir)
	all := []search.Source{
		projectSource(roots),
		a.sessionSource(roots),
		a.pluginSource(),
		a.swarmSource(),
		&fileSource{index: a.FileIndex, roots: roots, active: activeRoot(roots, dir)},
	}
	sources := filterKinds(all, c.Query("kinds"))

	res := search.Run(ctx, q, sources, limit)
	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"hits": res.Hits, "truncated": res.Truncated, "indexing": res.Indexing,
		"tookMs": time.Since(started).Milliseconds(),
	}})
}

// activeRoot dir 参数落在哪个项目根下（最长前缀）——那个项目的文件搜索时加分。
func activeRoot(roots []projRoot, dir string) string {
	if dir == "" || !filepath.IsAbs(dir) {
		return ""
	}
	dir = filepath.Clean(dir)
	best := ""
	for _, r := range roots {
		if (dir == r.dir || strings.HasPrefix(dir, r.dir+string(filepath.Separator))) && len(r.dir) > len(best) {
			best = r.dir
		}
	}
	return best
}

// filterKinds kinds 参数（逗号分隔）挑数据源；空 = 全要。
func filterKinds(all []search.Source, raw string) []search.Source {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return all
	}
	want := map[string]bool{}
	for _, k := range strings.Split(raw, ",") {
		want[strings.TrimSpace(k)] = true
	}
	out := make([]search.Source, 0, len(all))
	for _, s := range all {
		if want[s.Kind()] {
			out = append(out, s)
		}
	}
	if len(out) == 0 {
		return all
	}
	return out
}

type contentHit struct {
	Path       string `json:"path"`
	Rel        string `json:"rel"`
	Line       int    `json:"line"`
	Text       string `json:"text"`
	ProjectKey string `json:"projectKey,omitempty"`
	Project    string `json:"project,omitempty"`
}

// SearchContent GET /search/content?q=<字面量>[&dir=<根>][&limit=N]
//
// 内容搜索是另一件事，所以是另一条接口：它要跑 rg/grep 读文件内容，比名字匹配贵
// 一到两个数量级，不能挂在每次按键上——前端把它做成显式的第二步。
// 查询按**字面量**处理（rg -F / grep -F）：搜索框里输 `foo(` 的人想找的是这几个字符，
// 不是一个正则；正则的报错信息更没法在一个搜索框里解释。
func (a *API) SearchContent(c *gin.Context) {
	started := time.Now()
	q := strings.TrimSpace(c.Query("q"))
	if len(q) < 2 {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"hits": []contentHit{}, "truncated": false, "tookMs": 0}})
		return
	}
	limit := clampInt(c.Query("limit"), maxContentHits, 1, 200)

	roots := a.projectRoots(c.Query("dir"))
	if dir := strings.TrimSpace(c.Query("dir")); dir != "" && filepath.IsAbs(dir) {
		roots = []projRoot{{name: filepath.Base(dir), dir: filepath.Clean(dir)}} // 指定了目录就只搜它
	} else if len(roots) > 8 {
		roots = roots[:8] // 全文按项目逐个跑，根太多必然超时，先扫前几个
	}
	if len(roots) == 0 {
		c.JSON(http.StatusOK, gin.H{"data": gin.H{"hits": []contentHit{}, "truncated": false, "tookMs": 0}})
		return
	}

	ctx, cancel := context.WithTimeout(c.Request.Context(), 8*time.Second)
	defer cancel()

	// 各根并行跑：串着来的话，八个项目 × 每个几百毫秒必然吃满超时，
	// 而用户等的是「这一下搜完没有」，不是「第几个项目搜完了」。
	per := limit/len(roots) + 1
	found := make([][]contentHit, len(roots))
	cuts := make([]bool, len(roots))
	var wg sync.WaitGroup
	for i, r := range roots {
		wg.Add(1)
		go func(i int, r projRoot) {
			defer wg.Done()
			hs, cut := grepRoot(ctx, q, r.dir, per)
			for j := range hs {
				hs[j].ProjectKey, hs[j].Project = r.key, r.name
			}
			found[i], cuts[i] = hs, cut
		}(i, r)
	}
	wg.Wait()

	hits := []contentHit{}
	truncated := ctx.Err() != nil
	for i := range found {
		if cuts[i] {
			truncated = true
		}
		for _, f := range found[i] {
			if len(hits) >= limit {
				truncated = true
				break
			}
			hits = append(hits, f)
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{
		"hits": hits, "truncated": truncated, "tookMs": time.Since(started).Milliseconds(),
	}})
}

// grepRoot 在一个根下跑 rg（没装则 grep），返回至多 limit 条 `文件:行号:正文`。
func grepRoot(ctx context.Context, q, dir string, limit int) ([]contentHit, bool) {
	var cmd *exec.Cmd
	if rg, err := exec.LookPath("rg"); err == nil {
		cmd = exec.CommandContext(ctx, rg,
			"--color", "never", "--no-heading", "--line-number", "--fixed-strings",
			"--ignore-case", "--max-count", "3", "--max-filesize", "2M",
			"--glob", "!.git", "--glob", "!node_modules", "--", q, dir)
	} else {
		cmd = exec.CommandContext(ctx, "grep", "-rIn", "--binary-files=without-match",
			"--exclude-dir=.git", "--exclude-dir=node_modules", "--exclude-dir=dist",
			"-F", "-i", "-e", q, dir)
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		return nil, false
	}
	if err := cmd.Start(); err != nil {
		return nil, false
	}
	hits := []contentHit{}
	truncated := false
	sc := bufio.NewScanner(stdout)
	sc.Buffer(make([]byte, 0, 64*1024), 512*1024)
	for sc.Scan() {
		if len(hits) >= limit {
			truncated = true
			break
		}
		path, rest, ok := strings.Cut(sc.Text(), ":")
		if !ok {
			continue
		}
		lineNo, text, ok := strings.Cut(rest, ":")
		if !ok {
			continue
		}
		n, err := strconv.Atoi(lineNo)
		if err != nil {
			continue
		}
		rel, rerr := filepath.Rel(dir, path)
		if rerr != nil {
			rel = path
		}
		hits = append(hits, contentHit{
			Path: path, Rel: filepath.ToSlash(rel), Line: n, Text: clipLine(text),
		})
	}
	// 命中够了就掐掉进程：一个常见词在大仓库里能吐几十万行，读完纯属浪费
	_ = cmd.Process.Kill()
	_ = cmd.Wait()
	return hits, truncated
}

// clipLine 把一行两端的空白去掉并截短——面板一行放不下 200 列的代码。
func clipLine(s string) string {
	s = strings.TrimSpace(strings.ReplaceAll(s, "\t", "  "))
	r := []rune(s)
	if len(r) > 200 {
		return string(r[:200]) + "…"
	}
	return s
}

func clampInt(raw string, def, lo, hi int) int {
	n, err := strconv.Atoi(strings.TrimSpace(raw))
	if err != nil {
		return def
	}
	if n < lo {
		return lo
	}
	if n > hi {
		return hi
	}
	return n
}

func sortRoots(roots []projRoot) {
	sort.Slice(roots, func(i, j int) bool { return roots[i].name < roots[j].name })
}

var osStat = os.Stat

// shortenPath 把家目录压成 ~，副标题里一长串 /home/xxx 只是噪音。
func shortenPath(p string) string {
	if p == "" {
		return ""
	}
	if home, err := os.UserHomeDir(); err == nil && home != "" {
		if p == home {
			return "~"
		}
		if strings.HasPrefix(p, home+string(filepath.Separator)) {
			return "~" + p[len(home):]
		}
	}
	return p
}
