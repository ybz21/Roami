package api

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/ttmux"
)

func TestMemoryActionsPreserveDeferredAndUnsupportedErrors(t *testing.T) {
	for _, code := range []string{"MEMORY_COMPACT_DEFERRED", "MEMORY_COMPACT_UNSUPPORTED"} {
		t.Run(code, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "session-cli")
			if err := os.WriteFile(path, []byte("#!/bin/sh\necho "+code+" >&2\nexit 1\n"), 0700); err != nil {
				t.Fatal(err)
			}
			a := &API{TT: ttmux.New(path)}
			r := gin.New()
			r.POST("/sessions/:name/compact", a.SessionCompact)
			w := httptest.NewRecorder()
			r.ServeHTTP(w, httptest.NewRequest(http.MethodPost, "/sessions/one/compact", nil))
			if w.Code != http.StatusConflict || !strings.Contains(w.Body.String(), code) {
				t.Fatalf("%d %s", w.Code, w.Body.String())
			}
		})
	}
}

func TestMemorySetupDownloadContainsOnlyReviewedScript(t *testing.T) {
	a := &API{}
	r := gin.New()
	r.GET("/memory/setup-script", a.MemorySetupScript)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, httptest.NewRequest(http.MethodGet, "/memory/setup-script", nil))
	if w.Code != http.StatusOK || !strings.Contains(w.Header().Get("Content-Disposition"), "roami-zram-setup.sh") || !strings.Contains(w.Body.String(), "memory_limit") || strings.Contains(w.Body.String(), "swapoff -a") {
		t.Fatalf("invalid administrator script download: %d", w.Code)
	}
}
