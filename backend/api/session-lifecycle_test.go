package api

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
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
	"github.com/ybz21/Roami/internal/gitcontext"
	"github.com/ybz21/Roami/internal/memguard"
	life "github.com/ybz21/Roami/internal/sessionlifecycle"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func TestSessionLifecycleIsolatedE2E(t *testing.T) {
	if os.Getenv("ROAMI_LIFECYCLE_TEST_CHILD") != "1" {
		if _, err := exec.LookPath("tmux"); err != nil {
			t.Skip("tmux is unavailable")
		}
		root, _ := filepath.Abs("../..")
		directory := t.TempDir()
		launcher := filepath.Join(root, "scripts/dev/isolated-roami.sh")
		t.Cleanup(func() {
			out, err := exec.Command(launcher, directory, "--stop").CombinedOutput()
			if err != nil {
				t.Errorf("isolated cleanup: %v %s", err, out)
			}
		})
		ctx, cancel := context.WithTimeout(context.Background(), 150*time.Second)
		defer cancel()
		cmd := exec.CommandContext(ctx, launcher, directory, "env", "ROAMI_LIFECYCLE_TEST_CHILD=1", os.Args[0], "-test.run=^TestSessionLifecycleIsolatedE2E$", "-test.v")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("isolated fixture: %v\n%s", err, out)
		}
		if strings.Contains(string(out), "--- SKIP: TestSessionLifecycleIsolatedE2E") {
			t.Skip("dedicated tmux pane scopes unavailable in isolated fixture")
		}
		t.Log(string(out))
		return
	}
	ctx := context.Background()
	rt := runtime.New()
	if _, err := memguard.CapturePaneStopProof(rt.PanePIDs("_roami-test")); err != nil {
		t.Skip("dedicated tmux pane scopes unavailable")
	}
	h := New(ttmux.New("roami"), "", rt.DataDir, "")
	router := gin.New()
	router.POST("/operations", h.LifecycleAccept)
	router.GET("/operations", h.LifecycleList)
	router.POST("/operations/:operation/:action", h.LifecycleAction)
	router.GET("/sessions/:name/worktree-status", h.SessionWorktreeStatus)
	call := func(method, path string, body any) *httptest.ResponseRecorder {
		t.Helper()
		encoded, _ := json.Marshal(body)
		r := httptest.NewRecorder()
		router.ServeHTTP(r, httptest.NewRequest(method, path, bytes.NewReader(encoded)))
		return r
	}
	repo := t.TempDir()
	git := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
		cmd.Env = append(gitcontext.ForDirectory(os.Environ()), "GIT_AUTHOR_NAME=test", "GIT_AUTHOR_EMAIL=test@example.invalid", "GIT_COMMITTER_NAME=test", "GIT_COMMITTER_EMAIL=test@example.invalid")
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	git("init", "-b", "main")
	if err := os.WriteFile(filepath.Join(repo, "first"), []byte("initial"), 0600); err != nil {
		t.Fatal(err)
	}
	git("add", ".")
	git("commit", "-m", "initial")
	marker := filepath.Join(repo, "launch-result")
	command := "python3 -c " + shellQuote("import pathlib,sys;pathlib.Path("+fmt.Sprintf("%q", marker)+").write_text(sys.argv[1])")
	intent := life.Intent{Name: "async fixture", Dir: repo, Worktree: true, Launch: &life.Launch{Command: command, Agent: "codex", Task: "Keep 'quotes' and $(literal) intact", Preamble: "{{PATH}}\n{{SESSION}}", TaskHeading: "Task", SetupHeading: "Setup"}}
	request := map[string]any{"kind": "create", "requestKey": "create-e2e-unique", "intent": intent}
	accepted := call("POST", "/operations", request)
	if accepted.Code != http.StatusAccepted {
		t.Fatal(accepted.Body.String())
	}
	var response struct {
		Data life.Operation `json:"data"`
	}
	if err := json.Unmarshal(accepted.Body.Bytes(), &response); err != nil {
		t.Fatal(err)
	}
	o := response.Data
	if identity, err := rt.SessionIdentity(o.ResourceID); err != nil || identity != "" {
		t.Fatal("acceptance executed resource work synchronously")
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatal("launch happened before background worker")
	}
	duplicate := call("POST", "/operations", request)
	var replay struct {
		Data life.Operation `json:"data"`
	}
	_ = json.Unmarshal(duplicate.Body.Bytes(), &replay)
	if duplicate.Code != http.StatusAccepted || replay.Data.ID != o.ID || replay.Data.ResourceID != o.ResourceID {
		t.Fatal("duplicate request allocated a second resource")
	}
	worker := life.Worker{Store: h.Lifecycle, Steps: h.lifecycleSteps}
	if err := worker.RunOne(ctx, o.ID); err != nil {
		t.Fatal(err)
	}
	created, err := h.Lifecycle.Get(o.ID)
	if err != nil || created.State != "succeeded" {
		t.Fatalf("create: %+v %v", created, err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for {
		if _, err = os.Stat(marker); err == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("background launch did not execute")
		}
		time.Sleep(20 * time.Millisecond)
	}
	data, err := os.ReadFile(marker)
	if err != nil {
		t.Fatal(err)
	}
	prepared, err := life.Result[lifecycleWorkspace](created, "workspace")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(data), intent.Launch.Task) || !strings.Contains(string(data), prepared.Path) || !strings.Contains(string(data), o.ResourceID) {
		t.Fatalf("lost original input or actual identity: %s", data)
	}
	status := call("GET", "/sessions/"+o.ResourceID+"/worktree-status", nil)
	var st struct {
		Data struct {
			Snapshot        string `json:"snapshot"`
			SessionIdentity string `json:"sessionIdentity"`
		}
	}
	_ = json.Unmarshal(status.Body.Bytes(), &st)
	if st.Data.Snapshot == "" || st.Data.SessionIdentity == "" {
		t.Fatalf("no confirmation identity: %s", status.Body.String())
	}
	if err = rt.SetPaused(o.ResourceID, true, "manual"); err != nil {
		t.Fatal(err)
	}
	closeRequest := map[string]any{"kind": "close", "requestKey": "close-e2e-unique", "resourceId": o.ResourceID, "intent": life.Intent{Mode: "discard", Path: prepared.Path, Snapshot: st.Data.Snapshot, SessionIdentity: st.Data.SessionIdentity}}
	closing := call("POST", "/operations", closeRequest)
	if closing.Code != http.StatusAccepted {
		t.Fatal(closing.Body.String())
	}
	_ = json.Unmarshal(closing.Body.Bytes(), &response)
	if err = rt.SendShellCommand("="+o.ResourceID, "echo should-not-run"); err == nil {
		t.Fatal("closing session accepted new input")
	}
	if _, err = rt.CreateSession(runtime.CreateOpts{Label: "late occupant", Dir: prepared.Path}); err == nil {
		t.Fatal("closing workspace accepted a new occupant")
	}
	if err = worker.RunOne(ctx, response.Data.ID); err != nil {
		t.Fatal(err)
	}
	closed, err := h.Lifecycle.Get(response.Data.ID)
	if err != nil || closed.State != "succeeded" || !closed.Has("stop") || !closed.Has("remove") {
		t.Fatalf("close: %+v %v", closed, err)
	}
	if current, err := rt.SessionIdentity(o.ResourceID); err != nil || current != "" {
		t.Fatal("session survived confirmed stop")
	}
	if _, err = os.Stat(prepared.Path); !os.IsNotExist(err) {
		t.Fatal("worktree survived successful cleanup")
	}
	if strings.Contains(git("worktree", "list", "--porcelain"), prepared.Path) {
		t.Fatal("worktree registration survived cleanup")
	}
	if err = worker.RunOne(ctx, closed.ID); err != nil {
		t.Fatal(err)
	}
	newFixture := func(name string, launch *life.Launch) life.Operation {
		t.Helper()
		r := call("POST", "/operations", map[string]any{"kind": "create", "requestKey": "create-" + name, "intent": life.Intent{Name: name, Dir: repo, Worktree: true, Launch: launch}})
		if r.Code != http.StatusAccepted {
			t.Fatal(r.Body.String())
		}
		_ = json.Unmarshal(r.Body.Bytes(), &response)
		if err := worker.RunOne(ctx, response.Data.ID); err != nil {
			t.Fatal(err)
		}
		created, err := h.Lifecycle.Get(response.Data.ID)
		if err != nil || created.State != "succeeded" {
			t.Fatalf("fixture create: %s %s %v", created.Stage, created.ErrorDetail, err)
		}
		return created
	}
	closeFixture := func(created life.Operation, mode string) life.Operation {
		t.Helper()
		workspace, e := life.Result[lifecycleWorkspace](created, "workspace")
		if e != nil {
			t.Fatal(e)
		}
		identity, e := rt.SessionIdentity(created.ResourceID)
		if e != nil {
			t.Fatal(e)
		}
		snapshot, e := h.WT.Snapshot(ctx, workspace.Path)
		if e != nil {
			t.Fatal(e)
		}
		r := call("POST", "/operations", map[string]any{"kind": "close", "resourceId": created.ResourceID, "requestKey": "close-" + created.ID, "intent": life.Intent{Mode: mode, Strategy: "squash", Path: workspace.Path, SessionIdentity: identity, Snapshot: snapshot}})
		if r.Code != http.StatusAccepted {
			t.Fatal(r.Body.String())
		}
		_ = json.Unmarshal(r.Body.Bytes(), &response)
		return response.Data
	}
	// Content written after confirmation survives; retention resumes without reviving the executor.
	changed := newFixture("changed-fixture", nil)
	changedWorkspace, _ := life.Result[lifecycleWorkspace](changed, "workspace")
	changedClose := closeFixture(changed, "discard")
	lateFile := filepath.Join(changedWorkspace.Path, "late-user-file")
	if err = os.WriteFile(lateFile, []byte("preserve"), 0600); err != nil {
		t.Fatal(err)
	}
	if err = worker.RunOne(ctx, changedClose.ID); err != nil {
		t.Fatal(err)
	}
	failed, _ := h.Lifecycle.Get(changedClose.ID)
	if failed.State != "attention" || failed.ErrorCode != "LIFECYCLE_WORKSPACE_CHANGED" || !failed.Has("stop") {
		t.Fatalf("late content protection: %s %s", failed.State, failed.ErrorDetail)
	}
	retained := call("POST", "/operations/"+failed.ID+"/retain", map[string]any{"revision": failed.Revision, "requestKey": "retain-changed-fixture"})
	if retained.Code != http.StatusAccepted {
		t.Fatal(retained.Body.String())
	}
	if err = worker.RunOne(ctx, failed.ID); err != nil {
		t.Fatal(err)
	}
	kept, _ := h.Lifecycle.Get(failed.ID)
	if kept.State != "succeeded" || kept.Intent.Mode != "keep" || kept.OriginalIntent.Mode != "discard" {
		t.Fatal("retention lost original intent")
	}
	if data, e := os.ReadFile(lateFile); e != nil || string(data) != "preserve" {
		t.Fatal("late content was deleted")
	}
	// A completed merge is a checkpoint even when removal subsequently fails.
	if err = os.Remove(marker); err != nil {
		t.Fatal(err)
	}
	merging := newFixture("merge-fixture", nil)
	mergeWorkspace, _ := life.Result[lifecycleWorkspace](merging, "workspace")
	if err = os.WriteFile(filepath.Join(mergeWorkspace.Path, "merged-file"), []byte("merged content"), 0600); err != nil {
		t.Fatal(err)
	}
	mergingClose := closeFixture(merging, "merge")
	mergeCalls := 0
	removeCalls := 0
	mergeWorker := life.Worker{Store: h.Lifecycle, Steps: func(o life.Operation) []life.Step {
		steps := h.lifecycleSteps(o)
		for i := range steps {
			run := steps[i].Run
			if steps[i].Name == "merge" {
				steps[i].Run = func(ctx context.Context, o life.Operation) (any, error) { mergeCalls++; return run(ctx, o) }
			}
			if steps[i].Name == "remove" {
				steps[i].Run = func(ctx context.Context, o life.Operation) (any, error) {
					removeCalls++
					if removeCalls == 1 {
						return nil, fmt.Errorf("fixture removal blocked")
					}
					return run(ctx, o)
				}
			}
		}
		return steps
	}}
	if err = mergeWorker.RunOne(ctx, mergingClose.ID); err != nil {
		t.Fatal(err)
	}
	mergeFailed, _ := h.Lifecycle.Get(mergingClose.ID)
	if mergeFailed.State != "attention" || !mergeFailed.Has("merge") || !mergeFailed.Has("stop") {
		t.Fatalf("merge checkpoint: %s %s", mergeFailed.Stage, mergeFailed.ErrorDetail)
	}
	mergedHead := git("rev-parse", "HEAD")
	retry := call("POST", "/operations/"+mergeFailed.ID+"/retry", map[string]any{"revision": mergeFailed.Revision, "requestKey": "retry-merged-fixture"})
	if retry.Code != http.StatusAccepted {
		t.Fatal(retry.Body.String())
	}
	if err = mergeWorker.RunOne(ctx, mergeFailed.ID); err != nil {
		t.Fatal(err)
	}
	mergeDone, _ := h.Lifecycle.Get(mergeFailed.ID)
	if mergeDone.State != "succeeded" || mergeCalls != 1 || git("rev-parse", "HEAD") != mergedHead {
		t.Fatalf("merge replayed on retry: %s %s calls=%d", mergeDone.State, mergeDone.ErrorDetail, mergeCalls)
	}
	// A launch side effect without a checkpoint is observed as unknown, never submitted twice.
	ambiguousMarker := filepath.Join(repo, "ambiguous-launch")
	ambiguousIntent := life.Intent{Name: "ambiguous-fixture", Dir: repo, Worktree: true, Launch: &life.Launch{Command: "python3 -c " + shellQuote("import pathlib;pathlib.Path("+fmt.Sprintf("%q", ambiguousMarker)+").open('a').write('launched\\n')"), Agent: "codex"}}
	acceptedAmbiguous := call("POST", "/operations", map[string]any{"kind": "create", "requestKey": "ambiguous-fixture", "intent": ambiguousIntent})
	if acceptedAmbiguous.Code != http.StatusAccepted {
		t.Fatal(acceptedAmbiguous.Body.String())
	}
	_ = json.Unmarshal(acceptedAmbiguous.Body.Bytes(), &response)
	ambiguous := response.Data
	interruptedContext, interrupt := context.WithCancel(ctx)
	interruptedWorker := life.Worker{Store: h.Lifecycle, Steps: func(o life.Operation) []life.Step {
		steps := h.lifecycleSteps(o)
		for i := range steps {
			if steps[i].Name == "launch" {
				run := steps[i].Run
				steps[i].Run = func(ctx context.Context, o life.Operation) (any, error) {
					result, e := run(ctx, o)
					if e != nil {
						return result, e
					}
					interrupt()
					return result, context.Canceled
				}
			}
		}
		return steps
	}}
	if err = interruptedWorker.RunOne(interruptedContext, ambiguous.ID); err != context.Canceled {
		t.Fatalf("no injected interruption: %v", err)
	}
	deadline = time.Now().Add(3 * time.Second)
	for {
		if _, e := os.Stat(ambiguousMarker); e == nil {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("launch side effect missing")
		}
		time.Sleep(20 * time.Millisecond)
	}
	if err = worker.RunOne(ctx, ambiguous.ID); err != nil {
		t.Fatal(err)
	}
	unknown, _ := h.Lifecycle.Get(ambiguous.ID)
	if unknown.State != "attention" || unknown.ErrorCode != "LIFECYCLE_RESULT_UNKNOWN" {
		t.Fatalf("unknown launch was replayed: %s %s", unknown.State, unknown.ErrorDetail)
	}
	launched, e := os.ReadFile(ambiguousMarker)
	if e != nil || string(launched) != "launched\n" {
		t.Fatalf("duplicate launch: %q %v", launched, e)
	}
	cancelRequest := call("POST", "/operations/"+unknown.ID+"/cancel", map[string]any{"revision": unknown.Revision, "requestKey": "cancel-ambiguous-fixture"})
	if cancelRequest.Code != http.StatusAccepted {
		t.Fatal(cancelRequest.Body.String())
	}
	if err = worker.RunOne(ctx, unknown.ID); err != nil {
		t.Fatal(err)
	}
	cancelled, _ := h.Lifecycle.Get(unknown.ID)
	if cancelled.State != "cancelled" {
		t.Fatalf("cancellation: %s %s", cancelled.Stage, cancelled.ErrorDetail)
	}

	// Even an ignored file written by a post-commit hook remains unconfirmed user data.
	hookFixture := newFixture("posthook-fixture", nil)
	hookWorkspace, _ := life.Result[lifecycleWorkspace](hookFixture, "workspace")
	if err = os.WriteFile(filepath.Join(hookWorkspace.Path, ".gitignore"), []byte(".late-hook-file\n"), 0600); err != nil {
		t.Fatal(err)
	}
	hookClose := closeFixture(hookFixture, "merge")
	hookPath := filepath.Join(repo, ".git", "hooks", "post-commit")
	hookScript := "#!/bin/sh\nif [ \"$PWD\" = " + shellQuote(hookWorkspace.Path) + " ]; then printf 'keep hook output' > .late-hook-file; fi\n"
	if err = os.WriteFile(hookPath, []byte(hookScript), 0700); err != nil {
		t.Fatal(err)
	}
	if err = worker.RunOne(ctx, hookClose.ID); err != nil {
		t.Fatal(err)
	}
	hookResult, _ := h.Lifecycle.Get(hookClose.ID)
	if hookResult.State != "attention" || hookResult.Stage != "commit" || hookResult.ErrorCode != "LIFECYCLE_WORKSPACE_CHANGED" {
		t.Fatalf("late ignored data was accepted: %s %s %s", hookResult.State, hookResult.Stage, hookResult.ErrorDetail)
	}
	if body, e := os.ReadFile(filepath.Join(hookWorkspace.Path, ".late-hook-file")); e != nil || string(body) != "keep hook output" {
		t.Fatal("late hook data was deleted")
	}

}
