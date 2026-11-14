package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/ttmux"
	"github.com/ybz21/Roami/backend/worktree"
	"github.com/ybz21/Roami/internal/gitcontext"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestWorktreeCloseStatusSync(t *testing.T) {
	if os.Getenv("ROAMI_CLOSE_STATUS_TEST_CHILD") != "1" {
		if _, err := exec.LookPath("tmux"); err != nil {
			t.Skip("tmux is unavailable")
		}
		root, _ := filepath.Abs("../..")
		directory := t.TempDir()
		launcher := filepath.Join(root, "scripts/dev/isolated-roami.sh")
		t.Cleanup(func() {
			if out, err := exec.Command(launcher, directory, "--stop").CombinedOutput(); err != nil {
				t.Errorf("isolated cleanup: %v %s", err, out)
			}
		})
		ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, launcher, directory, "env", "ROAMI_CLOSE_STATUS_TEST_CHILD=1", os.Args[0], "-test.run=^TestWorktreeCloseStatusSync$", "-test.v")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("isolated close precheck: %v\n%s", err, out)
		}
		t.Log(string(out))
		return
	}
	for _, kind := range []string{"ancestry", "squash", "squash-multiple"} {
		t.Run(kind, func(t *testing.T) {
			ctx := context.Background()
			rt := runtime.New()
			h := New(ttmux.New("roami"), "", rt.DataDir, "")
			router := gin.New()
			router.GET("/sessions/:name/worktree-status", h.SessionWorktreeStatus)
			repo := t.TempDir()
			git := func(dir string, args ...string) string {
				t.Helper()
				cmd := exec.Command("git", append([]string{"-C", dir}, args...)...)
				cmd.Env = append(gitcontext.ForDirectory(os.Environ()), "GIT_AUTHOR_NAME=test", "GIT_AUTHOR_EMAIL=test@example.invalid", "GIT_COMMITTER_NAME=test", "GIT_COMMITTER_EMAIL=test@example.invalid")
				out, err := cmd.CombinedOutput()
				if err != nil {
					t.Fatalf("git %v: %v %s", args, err, out)
				}
				return strings.TrimSpace(string(out))
			}
			commit := func(dir, file, contents string) {
				t.Helper()
				if err := os.WriteFile(filepath.Join(dir, file), []byte(contents), 0600); err != nil {
					t.Fatal(err)
				}
				git(dir, "add", file)
				git(dir, "commit", "-m", file)
			}
			git(repo, "init", "-b", "main")
			commit(repo, "initial", "initial")
			initial := git(repo, "rev-parse", "main")
			origin := filepath.Join(t.TempDir(), "origin.git")
			git(repo, "clone", "--bare", repo, origin)
			git(repo, "remote", "add", "origin", origin)
			git(repo, "fetch", "origin")
			wt, err := h.WT.Create(ctx, worktree.CreateReq{Dir: repo, Branch: "fix/close-status", Base: "main"})
			if err != nil {
				t.Fatal(err)
			}
			commit(wt.Path, "feature", "feature")
			if kind == "squash-multiple" {
				commit(wt.Path, "feature", "feature revised")
				commit(wt.Path, "another", "another feature")
			}
			name, err := rt.CreateSession(runtime.CreateOpts{Label: "close status", Dir: wt.Path})
			if err != nil {
				t.Fatal(err)
			}
			h.WT.BindSessionHome(name, wt.Path)
			others := 0
			status := func() worktree.Worktree {
				t.Helper()
				r := httptest.NewRecorder()
				router.ServeHTTP(r, httptest.NewRequest(http.MethodGet, "/sessions/"+name+"/worktree-status", nil))
				var result struct {
					Data struct {
						worktree.Worktree
						InWorktree      bool   `json:"inWorktree"`
						Snapshot        string `json:"snapshot"`
						SessionIdentity string `json:"sessionIdentity"`
						Others          int    `json:"others"`
					} `json:"data"`
				}
				if err := json.Unmarshal(r.Body.Bytes(), &result); err != nil || r.Code != http.StatusOK || !result.Data.InWorktree || result.Data.Snapshot == "" || result.Data.SessionIdentity == "" {
					t.Fatalf("invalid close precheck: %v %s", err, r.Body.String())
				}
				others = result.Data.Others
				return result.Data.Worktree
			}
			ahead := 1
			if kind == "squash-multiple" {
				ahead = 3
			}
			if st := status(); st.MergedInto != "" || st.CommittedAhead != ahead {
				t.Fatalf("unmerged work lost its warning: %+v", st)
			}
			head := git(wt.Path, "rev-parse", "HEAD")
			merged := head
			mergedKind := kind
			if strings.HasPrefix(kind, "squash") {
				merged = git(repo, "commit-tree", head+"^{tree}", "-p", initial, "-m", "squash feature")
				mergedKind = "squash"
			}
			git(repo, "push", "origin", merged+":refs/heads/main")
			// Emulate a merge from another clone without updating this checkout's refs.
			git(repo, "update-ref", "refs/remotes/origin/main", initial)
			if st := status(); st.MergedInto != "origin/main" || st.MergedKind != mergedKind {
				t.Fatalf("remote merge missing from close precheck: %+v", st)
			}
			if git(repo, "rev-parse", "main") != initial {
				t.Fatal("close precheck moved the local main branch")
			}
			attempt := filepath.Join(t.TempDir(), "ssh-attempt")
			ssh := filepath.Join(t.TempDir(), "ssh")
			if err := os.WriteFile(ssh, []byte("#!/bin/sh\nprintf attempt > "+shellQuote(attempt)+"\nexit 1\n"), 0700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("GIT_SSH_COMMAND", ssh)
			git(repo, "remote", "set-url", "origin", "ssh://unavailable.invalid/repo.git")
			if st := status(); st.MergedInto != "origin/main" {
				t.Fatalf("local merge evidence lost: %+v", st)
			}
			if _, err := os.Stat(attempt); !os.IsNotExist(err) {
				t.Fatal("already merged close precheck attempted a network connection")
			}
			peer, err := rt.CreateSession(runtime.CreateOpts{Label: "other occupant", Dir: wt.Path})
			if err != nil {
				t.Fatal(err)
			}
			h.WT.BindSessionHome(peer, wt.Path)
			status()
			if others != 1 {
				t.Fatalf("other worktree occupant missing from close precheck: %d", others)
			}
			if err := os.WriteFile(filepath.Join(wt.Path, "feature"), []byte("unsaved"), 0600); err != nil {
				t.Fatal(err)
			}
			if st := status(); st.MergedInto == "" || st.Dirty != 1 {
				t.Fatalf("merged work lost uncommitted changes warning: %+v", st)
			}
			git(repo, "remote", "set-url", "origin", filepath.Join(t.TempDir(), "unavailable.git"))
			if st := status(); st.MergedInto == "" || st.Dirty != 1 {
				t.Fatalf("unavailable remote lost local evidence: %+v", st)
			}
			git(repo, "remote", "remove", "origin")
			git(repo, "update-ref", "refs/heads/main", merged)
			if st := status(); st.MergedInto != "main" || st.Dirty != 1 {
				t.Fatalf("local-only repository cannot close safely: %+v", st)
			}
			commit(wt.Path, "feature", "followup")
			if st := status(); st.MergedInto != "" || st.CommittedAhead == 0 || st.Dirty != 0 {
				t.Fatalf("followup commit lost unmerged warning: %+v", st)
			}
			git(repo, "remote", "add", "origin", "ssh://unavailable.invalid/repo.git")
			if st := status(); st.MergedInto != "" || st.CommittedAhead == 0 {
				t.Fatalf("offline followup commit lost warning: %+v", st)
			}
			if _, err := os.Stat(attempt); err != nil {
				t.Fatal("new unmerged HEAD did not attempt to refresh remote evidence")
			}
			t.Log("Close precheck detects remote merge with stale local refs; dirty changes and offline/local fallback remain visible")
		})
	}
}
