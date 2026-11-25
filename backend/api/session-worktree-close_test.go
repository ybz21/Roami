package api

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/worktree"
	life "github.com/ybz21/Roami/internal/sessionlifecycle"
	metadb "github.com/ybz21/Roami/internal/storage"
)

func lifecycleAPI(t *testing.T) (*API, *gin.Engine) {
	t.Helper()
	directory := t.TempDir()
	db, err := metadb.Open(directory, metadb.Options{HomeDir: directory, DataDir: directory})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = metadb.Discard(db.Path()) })
	a := &API{Lifecycle: life.New(db, db.Path())}
	router := gin.New()
	router.POST("/operations", a.LifecycleAccept)
	router.POST("/operations/:operation/:action", a.LifecycleAction)
	return a, router
}

func TestLifecycleAcceptanceSurvivesClientDisconnect(t *testing.T) {
	a, router := lifecycleAPI(t)
	payload := map[string]any{"kind": "create", "requestKey": "disconnect-request", "intent": life.Intent{Name: "saved task", Dir: t.TempDir(), Task: "Keep this original request"}}
	data, _ := json.Marshal(payload)
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	request := httptest.NewRequest(http.MethodPost, "/operations", bytes.NewReader(data)).WithContext(ctx)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, request)
	if response.Code != http.StatusAccepted {
		t.Fatal(response.Body.String())
	}
	stored, err := a.Lifecycle.ByKey("disconnect-request")
	if err != nil || stored.State != "queued" || stored.Intent.Task != "Keep this original request" {
		t.Fatalf("lost durable intent: %+v %v", stored, err)
	}
}

func TestLifecycleRetryUsesSessionIDForLegacyImplicitBranch(t *testing.T) {
	a, router := lifecycleAPI(t)
	root := t.TempDir()
	isolateTestStorage(t, root)
	repo := e2eRepo(t, root)
	a.WT = worktree.New(root, nil)
	ctx := context.Background()
	git := func(args ...string) string {
		t.Helper()
		cmd := exec.Command("git", append([]string{"-C", repo}, args...)...)
		cmd.Env = scrubGitEnv()
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("git %v: %v %s", args, err, out)
		}
		return strings.TrimSpace(string(out))
	}
	const existing = "docs/unified-sdk-design"
	git("branch", existing)
	head := git("rev-parse", existing)
	session := "2026-1125-1102-k6gw"
	path := filepath.Join(repo, ".worktrees", session)
	o, err := a.Lifecycle.Accept("legacy-operation", session, "legacy-create-request", "create", life.Intent{Name: "整理下docs目录", Dir: repo, Worktree: true})
	if err != nil {
		t.Fatal(err)
	}
	_, legacyError := a.WT.Create(ctx, worktree.CreateReq{Dir: repo, Branch: "docs", Dirname: session, OperationID: o.ID, ExpectedPath: path})
	if legacyError == nil || !strings.Contains(legacyError.Error(), "refs/heads/"+existing) {
		t.Fatalf("fixture did not reproduce the name collision: %v", legacyError)
	}
	encoded, _ := json.Marshal(map[string]string{"path": path})
	o, err = a.Lifecycle.Mutate(o.ID, o.Revision, func(op *life.Operation) error {
		op.State, op.Stage, op.Epoch = "attention", "workspace", 3
		op.Receipts["workspace-intent"] = encoded
		op.ErrorCode, op.ErrorDetail = "LIFECYCLE_STEP_FAILED", legacyError.Error()
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	code, response := post(t, router, "/operations/"+o.ID+"/retry", map[string]any{"requestKey": "retry-legacy-create", "revision": o.Revision})
	if code != http.StatusAccepted {
		t.Fatalf("retry status=%d: %v", code, response)
	}
	worker := life.Worker{Store: a.Lifecycle, Steps: func(life.Operation) []life.Step {
		return []life.Step{{Name: "workspace", Run: a.lifecyclePrepareWorkspace}}
	}}
	if err = worker.RunOne(ctx, o.ID); err != nil {
		t.Fatal(err)
	}
	ready, err := a.Lifecycle.Get(o.ID)
	if err != nil || ready.State != "succeeded" || ready.ResourceID != session || ready.Epoch != 4 {
		t.Fatalf("retry did not finish the original operation: state=%s detail=%s err=%v", ready.State, ready.ErrorDetail, err)
	}
	workspace, err := life.Result[lifecycleWorkspace](ready, "workspace")
	if err != nil || workspace.Path != path || workspace.Branch != session || git("rev-parse", existing) != head {
		t.Fatalf("retry workspace=%+v err=%v", workspace, err)
	}
	t.Logf("Retry reused %s, created branch %s, and preserved %s", session, workspace.Branch, existing)
}

func TestLifecycleRetryActionIsIdempotentAndKeepsMergeReceipt(t *testing.T) {
	a, router := lifecycleAPI(t)
	o, err := a.Lifecycle.Accept("close-operation", "2026-1108-0000-00aa", "original-request", "close", life.Intent{Mode: "merge", Path: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	o, err = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error {
		o.State = "attention"
		o.Stage = "remove"
		o.Receipts["merge"] = json.RawMessage(`{"result":{"head":"confirmed"},"durationMs":1}`)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	body := map[string]any{"revision": o.Revision, "requestKey": "retry-request-key"}
	code, _ := post(t, router, "/operations/"+o.ID+"/retry", body)
	if code != http.StatusAccepted {
		t.Fatalf("retry status=%d", code)
	}
	first, _ := a.Lifecycle.Get(o.ID)
	code, _ = post(t, router, "/operations/"+o.ID+"/retry", body)
	if code != http.StatusAccepted {
		t.Fatalf("lost ack replay status=%d", code)
	}
	again, _ := a.Lifecycle.Get(o.ID)
	if first.Revision != again.Revision || !again.Has("merge") || again.OriginalIntent.Mode != "merge" || again.State != "queued" {
		t.Fatalf("retry replayed or lost completed work: %+v", again)
	}
	code, _ = post(t, router, "/operations/"+o.ID+"/retain", body)
	if code != http.StatusConflict {
		t.Fatal("request key was reused for another action")
	}
}

func TestLifecycleRetentionCannotPretendRemovedWorkspaceStillExists(t *testing.T) {
	a, router := lifecycleAPI(t)
	o, err := a.Lifecycle.Accept("removed-operation", "2026-1108-0000-00bb", "removed-request", "close", life.Intent{Mode: "discard", Path: t.TempDir()})
	if err != nil {
		t.Fatal(err)
	}
	o, err = a.Lifecycle.Mutate(o.ID, o.Revision, func(o *life.Operation) error {
		o.State = "attention"
		o.Stage = "branch"
		o.Receipts["remove"] = json.RawMessage(`{"result":true,"durationMs":1}`)
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	code, _ := post(t, router, "/operations/"+o.ID+"/retain", map[string]any{"revision": o.Revision, "requestKey": "retain-directory"})
	if code != http.StatusConflict {
		t.Fatal("removed workspace was reported retained")
	}
	code, _ = post(t, router, "/operations/"+o.ID+"/retain-branch", map[string]any{"revision": o.Revision, "requestKey": "retain-local-branch"})
	if code != http.StatusAccepted {
		t.Fatal("branch could not be retained independently")
	}
	kept, _ := a.Lifecycle.Get(o.ID)
	if kept.Intent.Mode != "discard" || !kept.Intent.KeepBranch || !kept.Has("remove") {
		t.Fatal("branch retention changed directory outcome")
	}
}

func TestCloseWorktreeInspectionRejectsProtectedDirectories(t *testing.T) {
	directory := t.TempDir()
	repo := e2eRepo(t, directory)
	service := worktree.New("", nil)
	for _, path := range []string{repo, filepath.Join(repo, "subdirectory"), filepath.Join(directory, "missing"), directory} {
		if path == filepath.Join(repo, "subdirectory") {
			if err := os.Mkdir(path, 0700); err != nil {
				t.Fatal(err)
			}
		}
		if _, err := service.LifecycleDetails(context.Background(), path); err == nil {
			t.Fatalf("protected directory accepted: %s", path)
		}
	}
}
