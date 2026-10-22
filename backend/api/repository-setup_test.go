package api

import (
	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/worktree"
	"net/http"
	"testing"
)

func TestGitSetupAPI(t *testing.T) {
	a := &API{WT: worktree.New("", nil)}
	dir := t.TempDir()
	code, resp := call(t, a.GitIsRepo, "GET", "/x?path="+dir, nil)
	if code != http.StatusOK || dataOf(t, resp)["repo"] != false {
		t.Fatalf("plain directory: %d %v", code, resp)
	}
	code, resp = call(t, a.GitInitialize, "POST", "/x", gin.H{"dir": dir})
	if code != http.StatusOK || dataOf(t, resp)["hasCommits"] != true {
		t.Fatalf("initialize: %d %v", code, resp)
	}
	code, resp = call(t, a.GitIsRepo, "GET", "/x?path="+dir, nil)
	if code != http.StatusOK || dataOf(t, resp)["hasCommits"] != true {
		t.Fatalf("ready: %d %v", code, resp)
	}
	code, _ = call(t, a.GitInitialize, "POST", "/x", gin.H{"dir": "relative"})
	if code != http.StatusBadRequest {
		t.Fatalf("bad path: %d", code)
	}
}
