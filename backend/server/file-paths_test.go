package server

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"ttmux-web/api"
	"ttmux-web/auth"
)

func TestFilePathLinks(t *testing.T) {
	gin.SetMode(gin.TestMode)
	h := &api.API{}
	a := auth.New("test-password", "", "", 5, 60, nil)
	r := gin.New()
	r.UseRawPath = true
	r.POST("/login", a.Login)
	g := r.Group("/api", a.Middleware())
	g.GET("/file", h.File)
	g.GET("/file/raw", h.FileRaw)
	g.GET("/file/stat", h.FileStat)
	g.GET("/file/serve/*path", h.FileServe)
	g.HEAD("/file/serve/*path", h.FileServe)
	mountWeb(r, "", func(c *gin.Context) bool {
		return serveFilePath(c, a.Middleware(), h)
	})

	login := httptest.NewRecorder()
	r.ServeHTTP(login, httptest.NewRequest(http.MethodPost, "/login", strings.NewReader(`{"password":"test-password"}`)))
	if login.Code != http.StatusOK || len(login.Result().Cookies()) == 0 {
		t.Fatalf("login failed: %d %s", login.Code, login.Body.String())
	}
	cookie := login.Result().Cookies()[0]

	// Keep the fixture under cwd so relative paths can be tested without changing process cwd.
	dir, err := os.MkdirTemp(".", "file-paths-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(dir) })
	dir, err = filepath.Abs(dir)
	if err != nil {
		t.Fatal(err)
	}
	name := "预览 + 100% #?.html"
	path := filepath.Join(dir, name)
	const content = "<!doctype html><link rel=stylesheet href=style.css>"
	for name, body := range map[string]string{name: content, "index.html": content, "style.css": "body { color: red; }"} {
		if err := os.WriteFile(filepath.Join(dir, name), []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	rel, err := filepath.Rel(cwd, path)
	if err != nil {
		t.Fatal(err)
	}
	escape := func(p string) string { return (&url.URL{Path: filepath.ToSlash(p)}).EscapedPath() }
	for _, tc := range []struct {
		name, target, method, body string
		download, json             bool
	}{
		{name: "absolute", target: "/api/file" + escape(path), body: content},
		{name: "double separator", target: "/api/file/" + escape(path), body: content},
		{name: "encoded absolute", target: "/api/file/" + url.PathEscape(path), body: content},
		{name: "relative", target: "/api/file/" + escape(rel), body: content},
		{name: "raw absolute", target: "/api/file/raw" + escape(path), body: content},
		{name: "raw relative", target: "/api/file/raw/" + escape(rel), body: content},
		{name: "index", target: "/api/file" + escape(filepath.Join(dir, "index.html")), body: content},
		{name: "relative asset", target: "/api/file" + escape(filepath.Join(dir, "style.css")), body: "body { color: red; }"},
		{name: "download", target: "/api/file" + escape(path) + "?dl=1", body: content, download: true},
		{name: "serve head", target: "/api/file/serve" + escape(path), method: http.MethodHead},
		{name: "head", target: "/api/file" + escape(path), method: http.MethodHead},
		{name: "query raw", target: "/api/file/raw?path=" + url.QueryEscape(path), body: content},
		{name: "query content", target: "/api/file?path=" + url.QueryEscape(path), body: content, json: true},
		{name: "stat", target: "/api/file/stat?path=" + url.QueryEscape(path), json: true},
		{name: "serve", target: "/api/file/serve" + escape(filepath.Join(dir, "index.html")), body: content},
	} {
		t.Run(tc.name, func(t *testing.T) {
			method := tc.method
			if method == "" {
				method = http.MethodGet
			}
			req := httptest.NewRequest(method, tc.target, nil)
			req.AddCookie(cookie)
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			if w.Code != http.StatusOK {
				t.Fatalf("want 200, got %d: %s", w.Code, w.Body.String())
			}
			if tc.json {
				if !strings.HasPrefix(w.Header().Get("Content-Type"), "application/json") {
					t.Fatalf("expected JSON: %s", w.Body.String())
				}
			} else if w.Body.String() != tc.body {
				t.Fatalf("unexpected body: %q", w.Body.String())
			}
			if tc.download && !strings.HasPrefix(w.Header().Get("Content-Disposition"), "attachment;") {
				t.Fatalf("missing attachment disposition: %v", w.Header())
			}
			if method == http.MethodHead && w.Header().Get("X-Roami-File-Path") != url.PathEscape(path) {
				t.Fatalf("missing canonical path: %v", w.Header())
			}
			if w.Header().Get("Location") != "" {
				t.Fatalf("unexpected redirect: %v", w.Header())
			}
		})
	}

	t.Run("range", func(t *testing.T) {
		req := httptest.NewRequest(http.MethodGet, "/api/file"+escape(path), nil)
		req.AddCookie(cookie)
		req.Header.Set("Range", "bytes=0-3")
		w := httptest.NewRecorder()
		r.ServeHTTP(w, req)
		if w.Code != http.StatusPartialContent || w.Body.String() != content[:4] {
			t.Fatalf("unexpected range response: %d %q", w.Code, w.Body.String())
		}
		if w.Header().Get("Cache-Control") != "no-store" {
			t.Fatalf("missing no-store: %v", w.Header())
		}
	})

	for _, tc := range []struct {
		name, method, target string
		authorized           bool
		status               int
	}{
		{"anonymous", "GET", "/api/file" + escape(path), false, http.StatusUnauthorized},
		{"anonymous raw", "GET", "/api/file/raw" + escape(path), false, http.StatusUnauthorized},
		{"missing", "GET", "/api/file" + escape(filepath.Join(dir, "missing")), true, http.StatusBadRequest},
		{"directory", "GET", "/api/file" + escape(dir), true, http.StatusBadRequest},
		{"other API", "GET", "/api/missing", true, http.StatusNotFound},
		{"write", "POST", "/api/file" + escape(path), true, http.StatusNotFound},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(tc.method, tc.target, nil)
			if tc.authorized {
				req.AddCookie(cookie)
			}
			w := httptest.NewRecorder()
			r.ServeHTTP(w, req)
			if w.Code != tc.status {
				t.Fatalf("want %d, got %d: %s", tc.status, w.Code, w.Body.String())
			}
		})
	}
}
