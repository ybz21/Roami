package api

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"ttmux-web/project"
	"ttmux-web/worktree"
)

func TestDailyActivityDeduplicatesClonesAndReportsMissingProjects(t *testing.T) {
	dir := t.TempDir()
	repo, clone := filepath.Join(dir, "repo"), filepath.Join(dir, "clone")
	run := func(args ...string) {
		t.Helper()
		cmd := exec.Command("git", args...)
		for _, value := range os.Environ() {
			if !strings.HasPrefix(value, "GIT_") {
				cmd.Env = append(cmd.Env, value)
			}
		}
		cmd.Env = append(cmd.Env, "GIT_AUTHOR_NAME=test", "GIT_AUTHOR_EMAIL=test@example.com", "GIT_COMMITTER_NAME=test", "GIT_COMMITTER_EMAIL=test@example.com")
		if out, err := cmd.CombinedOutput(); err != nil {
			t.Fatalf("git failed: %v %s", err, out)
		}
	}
	run("init", "-b", "main", repo)
	run("-C", repo, "commit", "--allow-empty", "-m", "activity")
	run("clone", repo, clone)
	store := project.NewStore(filepath.Join(dir, "state"), nil)
	store.Add(repo, "")
	store.Add(clone, "")
	store.Add(dir, "") // A non-Git project is a valid project, not an error.
	store.Add(filepath.Join(dir, "missing"), "")
	a := &API{Projects: store, WT: worktree.New("", nil)}
	recorder := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(recorder)
	c.Request = httptest.NewRequest("GET", "/activity/daily", nil)
	a.DailyActivity(c)
	var response struct {
		Data struct {
			Commits              []worktree.ActivityCommit
			Repositories, Failed int
		}
	}
	if err := json.Unmarshal(recorder.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	if recorder.Code != 200 || len(response.Data.Commits) != 1 || response.Data.Repositories != 2 || response.Data.Failed != 1 {
		t.Fatalf("unexpected response: %s", recorder.Body.String())
	}
}
