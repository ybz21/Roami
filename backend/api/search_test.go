package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/backend/search"
)

// 只测不依赖 tmux 的两类（项目 / 项目文件）：会话那一段要真的有 tmux server，
// 归 e2e 管。
func newSearchAPI(t *testing.T, projectDir string) *API {
	t.Helper()
	store := project.NewStore(t.TempDir(), nil)
	store.Add(projectDir, "")
	a := &API{Projects: store, FileIndex: search.NewFileIndex()}
	a.FileIndex.Rebuild(projectDir) // 正常路径是后台建索引，测试里先同步建好，免得跟调度赛跑
	return a
}

func writeFile(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("hello search\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func runSearch(t *testing.T, a *API, query string) []search.Hit {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.GET("/search", a.Search)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/search?kinds=project,file&q="+query, nil))
	if w.Code != http.StatusOK {
		t.Fatalf("want 200, got %d: %s", w.Code, w.Body.String())
	}
	var resp struct {
		Data struct {
			Hits []search.Hit `json:"hits"`
		} `json:"data"`
	}
	if err := json.Unmarshal(w.Body.Bytes(), &resp); err != nil {
		t.Fatal(err)
	}
	return resp.Data.Hits
}

func TestSearchFindsProjectAndFiles(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "roamproj")
	writeFile(t, filepath.Join(dir, "src", "overview.tsx"))
	writeFile(t, filepath.Join(dir, "node_modules", "pkg", "overview.tsx"))
	a := newSearchAPI(t, dir)

	hits := runSearch(t, a, "overview")
	files := 0
	for _, h := range hits {
		if h.Kind != "file" {
			continue
		}
		files++
		if h.Path != filepath.Join(dir, "src", "overview.tsx") {
			t.Fatalf("node_modules 不该进结果，得到 %s", h.Path)
		}
		if h.Project != "roamproj" {
			t.Fatalf("文件结果应带项目名，得到 %q", h.Project)
		}
	}
	if files != 1 {
		t.Fatalf("应命中 1 个文件，得到 %d（%+v）", files, hits)
	}

	if got := runSearch(t, a, "roamproj"); len(got) == 0 || got[0].Kind != "project" {
		t.Fatalf("项目名应命中且排在最前：%+v", got)
	}
}

func TestSearchEmptyQueryReturnsNothing(t *testing.T) {
	dir := t.TempDir()
	writeFile(t, filepath.Join(dir, "a.txt"))
	if hits := runSearch(t, newSearchAPI(t, dir), ""); len(hits) != 0 {
		t.Fatalf("空查询不该有结果，得到 %+v", hits)
	}
}

func TestSearchFuzzyMatchesPath(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "proj")
	writeFile(t, filepath.Join(dir, "backend", "api", "search.go"))
	a := newSearchAPI(t, dir)

	// 首字母缩写 + 跨路径段的两段式查询都要能找到
	for _, q := range []string{"srch", "api+search"} {
		hits := runSearch(t, a, q)
		found := false
		for _, h := range hits {
			if h.Kind == "file" && filepath.Base(h.Path) == "search.go" {
				found = true
			}
		}
		if !found {
			t.Fatalf("查询 %q 应命中 search.go，得到 %+v", q, hits)
		}
	}
}
