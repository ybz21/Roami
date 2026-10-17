// 全局搜索的数据源。**加一类可搜的东西 = 在这里加一个 source，别处一行都不用改**
// （前端只认 Action 的三种动作，见 search/engine.go 的注释）。
//
// 现有五类：项目 / 会话 / 项目文件 / 插件 / 蜂群。
package api

import (
	"context"
	"encoding/json"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/ybz21/Roami/backend/search"
	"github.com/ybz21/Roami/backend/worktree"
)

// projRoot 是「一个项目目录」：文件源的搜索根，也是会话/文件结果上「属于哪个项目」的来源。
type projRoot struct{ key, name, dir string }

// projectRoots 台账里的项目 + dir 参数带进来的临时根（当前会话所在目录）。
func (a *API) projectRoots(extraDir string) []projRoot {
	roots := []projRoot{}
	for key, e := range a.Projects.Entries() {
		name := e.DisplayName
		if name == "" {
			name = filepath.Base(e.Dir)
		}
		roots = append(roots, projRoot{key: key, name: name, dir: filepath.Clean(e.Dir)})
	}
	// 稳定顺序：同分结果在两次搜索间不该换位置
	sortRoots(roots)
	extraDir = strings.TrimSpace(extraDir)
	if extraDir == "" || !filepath.IsAbs(extraDir) {
		return roots
	}
	extraDir = filepath.Clean(extraDir)
	for _, r := range roots {
		if r.dir == extraDir {
			return roots
		}
	}
	if st, err := osStat(extraDir); err == nil && st.IsDir() {
		roots = append(roots, projRoot{key: "", name: filepath.Base(extraDir), dir: extraDir})
	}
	return roots
}

// projectOf 路径 → 所属项目（最长前缀：worktree 嵌在主仓库下时取更具体的那个）。
func projectOf(roots []projRoot, path string) (key, name string) {
	best := ""
	for _, r := range roots {
		if r.dir == path || strings.HasPrefix(path, r.dir+string(filepath.Separator)) {
			if len(r.dir) > len(best) {
				best, key, name = r.dir, r.key, r.name
			}
		}
	}
	return key, name
}

// ── 项目 ───────────────────────────────────────────────────────────────
func projectSource(roots []projRoot) search.Source {
	return search.FuncSource{KindName: "project", Max: 6, List: func(context.Context) []search.Doc {
		docs := make([]search.Doc, 0, len(roots))
		for _, r := range roots {
			if r.key == "" {
				continue // dir 参数带进来的临时根不是项目
			}
			docs = append(docs, search.Doc{
				ID: r.key, Title: r.name, Subtitle: shortenPath(r.dir), Path: r.dir,
				Project: r.name, ProjKey: r.key,
				Action: search.Action{Type: "route", Target: "#/projects/" + urlPathEscape(r.key)},
			})
		}
		return docs
	}}
}

// ── 会话（**全部**，不只已打开的）─────────────────────────────────────
func (a *API) sessionSource(roots []projRoot) search.Source {
	return search.FuncSource{KindName: "session", Max: 8, List: func(ctx context.Context) []search.Doc {
		var list []sessListItem
		if out, err := a.TT.Run("ls", "--json"); err == nil {
			_ = json.Unmarshal([]byte(out), &list)
		}
		if len(list) == 0 {
			return nil
		}
		ann := a.cachedAnnotations(ctx)
		docs := make([]search.Doc, 0, len(list))
		for _, s := range list {
			label := s.Label
			if label == "" {
				label = s.Name
			}
			dir := ""
			if an := ann[s.Name]; an != nil {
				if an.Primary != nil && an.Primary.Repo != "" {
					dir = an.Primary.Repo
				} else if an.Home != "" {
					dir = an.Home
				}
			}
			pkey, pname := projectOf(roots, dir)
			sub := pname
			if sub == "" {
				sub = shortenPath(dir)
			}
			if label != s.Name { // 展示名与会话 id 不同时，副标题带上 id
				if sub != "" {
					sub += " · "
				}
				sub += s.Name
			}
			docs = append(docs, search.Doc{
				ID: s.Name, Title: label, Subtitle: sub, Path: dir,
				Project: pname, ProjKey: pkey,
				// 会话还能按 id / 所属项目搜到：用户可能只记得「那个在 roam 里的会话」
				Aliases: []string{s.Name, pname},
				Action:  search.Action{Type: "session", Target: s.Name},
			})
		}
		return docs
	}}
}

// ── 项目文件（名字）───────────────────────────────────────────────────
//
// 这一类自己实现 Source 而不是用 FuncSource：一次要吐几万条，先攒成切片等于每次
// 按键多分配几 MB。索引在后台建（见 search.FileIndex），Ready 报告建好了没有。
type fileSource struct {
	index *search.FileIndex
	roots []projRoot
	// active 当前会话所在的项目目录：它下面的文件加分。搜 `ovw` 时你要的多半是
	// 手头这个项目的 Overview.tsx，而不是另一个项目里反编译出来的
	// OnVideoNotWorkCallback.java——后者按字形还更「像」。
	active string
	ready  bool
	cut    bool
}

// 当前项目加分。比一档词首奖励略大，足以把同类结果拉到前面，又不足以把
// 「另一个项目里名字完全对上的那个」压下去。
const activeProjectBoost = 20

func (s *fileSource) Kind() string { return "file" }
func (s *fileSource) Limit() int   { return 24 }
func (s *fileSource) Ready() bool  { return s.ready }

func (s *fileSource) Each(ctx context.Context, emit func(search.Doc) bool) {
	s.ready = true
	for _, r := range s.roots {
		if ctx.Err() != nil {
			return
		}
		list, cut, ready := s.index.Files(r.dir)
		if cut {
			s.cut = true
		}
		if !ready {
			s.ready = false
		}
		boost := 0
		if s.active != "" && r.dir == s.active {
			boost = activeProjectBoost
		}
		for _, rel := range list {
			abs := filepath.Join(r.dir, rel)
			if !emit(search.Doc{
				ID: abs, Title: filepath.Base(rel), Subtitle: filepath.ToSlash(rel), Path: abs,
				Project: r.name, ProjKey: r.key, Boost: boost,
				Action: search.Action{Type: "file", Target: abs},
			}) {
				return
			}
		}
	}
}

// ── 插件 ───────────────────────────────────────────────────────────────
//
// 中英文显示名、插件 id、描述都要能搜到：用户搜「定时」找的是「定时任务（roam.cron）」，
// 而 manifest 里那一栏叫 displayName["zh-CN"]。
func (a *API) pluginSource() search.Source {
	return search.FuncSource{KindName: "plugin", Max: 6, List: func(context.Context) []search.Doc {
		var list []struct {
			Manifest struct {
				ID          string            `json:"id"`
				Name        string            `json:"name"`
				DisplayName map[string]string `json:"displayName"`
				Description map[string]string `json:"description"`
				Version     string            `json:"version"`
			} `json:"manifest"`
			Enabled bool `json:"enabled"`
		}
		out, err := a.cliJSON("plugins", "plugin", "ls", "--json")
		if err != nil {
			return nil
		}
		if json.Unmarshal([]byte(out), &list) != nil {
			return nil
		}
		docs := make([]search.Doc, 0, len(list))
		for _, p := range list {
			m := p.Manifest
			title := m.DisplayName["zh-CN"]
			if title == "" {
				title = m.DisplayName["en-US"]
			}
			if title == "" {
				title = m.Name
			}
			aliases := []string{m.ID, m.Name}
			for _, v := range m.DisplayName {
				aliases = append(aliases, v)
			}
			sub := m.Description["zh-CN"]
			if sub == "" {
				sub = m.Description["en-US"]
			}
			docs = append(docs, search.Doc{
				ID: m.ID, Title: title, Subtitle: clipLine(sub), Aliases: aliases,
				Action: search.Action{Type: "route", Target: "#/plugins"},
			})
		}
		return docs
	}}
}

// ── 蜂群 ───────────────────────────────────────────────────────────────
func (a *API) swarmSource() search.Source {
	return search.FuncSource{KindName: "swarm", Max: 6, List: func(context.Context) []search.Doc {
		var list []struct {
			ID     string `json:"id"`
			Name   string `json:"name"`
			Goal   string `json:"goal"`
			Status string `json:"status"`
			Alive  int    `json:"alive"`
		}
		out, err := a.cliJSON("swarms", "swarm", "ls", "--json")
		if err != nil {
			return nil
		}
		if json.Unmarshal([]byte(out), &list) != nil {
			return nil
		}
		docs := make([]search.Doc, 0, len(list))
		for _, s := range list {
			if s.Status == "archived" {
				continue // 归档的蜂群不进搜索：它们只会淹没在跑的那几个
			}
			docs = append(docs, search.Doc{
				ID: s.ID, Title: s.Name, Subtitle: clipLine(s.Goal), Aliases: []string{s.ID},
				Action: search.Action{Type: "route", Target: "#/swarm/" + urlPathEscape(s.Name)},
			})
		}
		return docs
	}}
}

// ── 共用：CLI 读命令的短 TTL 缓存 ─────────────────────────────────────
//
// 搜索是打字时连着问的：插件列表、蜂群列表这类「一条 CLI 子进程」的读，每个按键
// 跑一次会把 CPU 白烧掉。5 秒缓存与前端 120ms 防抖配起来，一次输入最多跑一次。
var (
	cliCacheMu sync.Mutex
	cliCache   = map[string]struct {
		at  time.Time
		out string
		err error
	}{}
)

func (a *API) cliJSON(key string, args ...string) (string, error) {
	cliCacheMu.Lock()
	if c, ok := cliCache[key]; ok && time.Since(c.at) < 5*time.Second {
		cliCacheMu.Unlock()
		return c.out, c.err
	}
	cliCacheMu.Unlock()

	out, err := a.TT.Run(args...)
	cliCacheMu.Lock()
	cliCache[key] = struct {
		at  time.Time
		out string
		err error
	}{time.Now(), out, err}
	cliCacheMu.Unlock()
	return out, err
}

// cachedAnnotations 会话 → 归属目录，15s 缓存：那一趟要按会话拉子进程，
// 每个按键重算一次会把 tmux 拖垮。
var (
	annCacheMu sync.Mutex
	annCacheAt time.Time
	annCache   map[string]*worktree.Annotation
)

func (a *API) cachedAnnotations(ctx context.Context) map[string]*worktree.Annotation {
	annCacheMu.Lock()
	if annCache != nil && time.Since(annCacheAt) < 15*time.Second {
		res := annCache
		annCacheMu.Unlock()
		return res
	}
	annCacheMu.Unlock()

	res := a.WT.Annotations(ctx)
	annCacheMu.Lock()
	annCache, annCacheAt = res, time.Now()
	annCacheMu.Unlock()
	return res
}
