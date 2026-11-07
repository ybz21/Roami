package api

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/project"
	"github.com/ybz21/Roami/backend/ttmux"
	"github.com/ybz21/Roami/backend/worktree"
)

func closeWorktreeFixture(t *testing.T, script string) (*gin.Engine, string, string) {
	t.Helper()
	tmp := t.TempDir()
	cli := filepath.Join(tmp, "session-cli")
	if err := os.WriteFile(cli, []byte("#!/bin/sh\n"+script), 0o755); err != nil {
		t.Fatal(err)
	}
	// No terminal observation in this fixture may reach the user's server.
	t.Setenv("TMUX_BIN", "/bin/false")
	repo := e2eRepo(t, tmp)
	wt := worktree.New("", nil)
	created, err := wt.Create(context.Background(), worktree.CreateReq{Dir: repo, Branch: "close-task", Base: "main"})
	if err != nil {
		t.Fatal(err)
	}
	a := &API{TT: ttmux.New(cli), WT: wt, Projects: project.NewStore(tmp, nil)}
	r := gin.New()
	r.POST("/sessions/:name/close-with-worktree", a.SessionCloseWithWorktree)
	return r, created.Path, tmp
}

func TestCloseWorktreeCompletesAfterClientDisconnect(t *testing.T) {
	r, path, tmp := closeWorktreeFixture(t, `if [ "$1" = kill ]; then
  touch "$CLOSE_STARTED"
  while [ ! -f "$CLOSE_RELEASE" ]; do sleep 0.01; done
fi
`)
	started, release := filepath.Join(tmp, "started"), filepath.Join(tmp, "release")
	t.Setenv("CLOSE_STARTED", started)
	t.Setenv("CLOSE_RELEASE", release)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	finished := make(chan struct{})
	go func() {
		defer close(finished)
		deadline := time.Now().Add(5 * time.Second)
		for time.Now().Before(deadline) {
			if _, err := os.Stat(started); err == nil {
				cancel()
				_ = os.WriteFile(release, nil, 0o600)
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
		cancel()
		_ = os.WriteFile(release, nil, 0o600)
	}()
	req := httptest.NewRequest(http.MethodPost, "/sessions/2026-1106-1442-00aa/close-with-worktree", bytes.NewBufferString(`{"mode":"discard","path":"`+path+`"}`)).WithContext(ctx)
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	<-finished
	if w.Code != http.StatusOK {
		t.Fatalf("close interrupted after kill: %d %s", w.Code, w.Body.String())
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("worktree survived client disconnect: %v", err)
	}
}

func TestCloseWorktreeRetriesAfterSessionAlreadyClosed(t *testing.T) {
	for _, snapshot := range []string{"[]", `[{"name":"2026-1106-1442-00aa"}]`, "invalid", "null", "[{}]"} {
		t.Run(snapshot, func(t *testing.T) {
			r, path, _ := closeWorktreeFixture(t, "case $1 in\nkill) echo 'session not found'; exit 1;;\nls) echo '"+snapshot+"';;\nesac\n")
			code, body := post(t, r, "/sessions/2026-1106-1442-00aa/close-with-worktree", map[string]any{"mode": "discard", "path": path})
			if snapshot == "[]" {
				if code != http.StatusOK {
					t.Fatalf("retry blocked by already closed session: %d %v", code, body)
				}
				if _, err := os.Stat(path); !os.IsNotExist(err) {
					t.Fatalf("worktree survived retry: %v", err)
				}
			} else if code != http.StatusConflict {
				t.Fatalf("unverified kill must block cleanup: %d %v", code, body)
			} else if _, err := os.Stat(path); err != nil {
				t.Fatalf("worktree removed without stop proof: %v", err)
			}
		})
	}
}

func TestCloseWorktreeInspectsBeforeClosingSession(t *testing.T) {
	for _, target := range []string{"main", "subdirectory", "missing", "not-git"} {
		t.Run(target, func(t *testing.T) {
			r, path, tmp := closeWorktreeFixture(t, "touch \"$CLOSE_STARTED\"\n")
			started := filepath.Join(tmp, "started")
			t.Setenv("CLOSE_STARTED", started)
			switch target {
			case "main":
				path = filepath.Join(tmp, "repo")
			case "subdirectory":
				path = filepath.Join(path, "sub")
				if err := os.Mkdir(path, 0o755); err != nil {
					t.Fatal(err)
				}
			case "missing":
				path = filepath.Join(tmp, "missing")
			case "not-git":
				path = tmp
			}
			code, body := post(t, r, "/sessions/2026-1106-1442-00aa/close-with-worktree", map[string]any{"mode": "discard", "path": path})
			if code != http.StatusConflict || body["error"].(map[string]any)["stage"] != "inspect" {
				t.Fatalf("expected inspection failure: %d %v", code, body)
			}
			if _, err := os.Stat(started); !os.IsNotExist(err) {
				t.Fatalf("session operation ran before inspection: %v", err)
			}
		})
	}
}

func TestCloseWorktreeRetriesAfterSquashAlreadyCompleted(t *testing.T) {
	t.Setenv("GIT_CONFIG_GLOBAL", os.DevNull)
	t.Setenv("GIT_CONFIG_NOSYSTEM", "1")
	r, path, _ := closeWorktreeFixture(t, "case $1 in\nkill) exit 1;;\nls) echo '[]';;\nesac\n")
	ctx := context.Background()
	wt := worktree.New("", nil)
	if err := os.WriteFile(filepath.Join(path, "feature.txt"), []byte("feature\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := wt.CommitAll(ctx, path, "feature"); err != nil {
		t.Fatal(err)
	}
	if _, err := wt.Merge(ctx, worktree.MergeReq{Path: path, Strategy: "squash"}); err != nil {
		t.Fatal(err)
	}
	code, body := post(t, r, "/sessions/2026-1106-1442-00aa/close-with-worktree", map[string]any{"mode": "merge", "path": path})
	if code != http.StatusOK {
		t.Fatalf("retry blocked after successful squash: %d %v", code, body)
	}
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Fatalf("worktree survived squash retry: %v", err)
	}
}
