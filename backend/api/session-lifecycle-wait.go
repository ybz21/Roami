package api

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/id"
	life "github.com/ybz21/Roami/internal/sessionlifecycle"
)

// Older clients wait for the same journal; only the new operation endpoint acknowledges immediately.
func (a *API) waitSessionLifecycle(c *gin.Context, kind, resource string, intent life.Intent) (life.Operation, bool) {
	if a.Lifecycle == nil {
		lifecycleError(c, context.Canceled)
		return life.Operation{}, false
	}
	key := c.GetHeader("Idempotency-Key")
	if key == "" {
		key = lifecycleID()
	}
	if resource == "" {
		resource = id.NewAt(time.Now())
	}
	o, err := a.Lifecycle.Accept(lifecycleID(), resource, key, kind, intent)
	if err != nil {
		lifecycleError(c, err)
		return o, false
	}
	worker := &life.Worker{Store: a.Lifecycle, Steps: a.lifecycleSteps}
	workerContext := a.lifecycleContext
	if workerContext == nil {
		workerContext = context.Background()
	}
	go func() { _ = worker.RunOne(workerContext, o.ID) }()
	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()
	for {
		o, err = a.Lifecycle.Get(o.ID)
		if err != nil {
			lifecycleError(c, err)
			return o, false
		}
		if o.Terminal() {
			return o, true
		}
		if o.State == "attention" {
			c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": o.ErrorCode, "message": o.ErrorDetail, "stage": o.Stage, "operationId": o.ID, "done": lifecycleDoneStages(o)}})
			return o, false
		}
		select {
		case <-c.Request.Context().Done():
			return o, false
		case <-ticker.C:
		}
	}
}

func lifecycleDoneStages(o life.Operation) []string {
	done := []string{}
	for _, stage := range []string{"stop", "commit", "merge", "remove"} {
		if !o.Has(stage) {
			continue
		}
		result, _ := life.Result[any](o, stage)
		if result == nil {
			continue
		}
		if stage == "stop" {
			stage = "kill"
		}
		if stage == "commit" {
			stage = "wip-commit"
		}
		done = append(done, stage)
	}
	return done
}

func (a *API) waitWorktreeCreate(c *gin.Context, parent, name, dir, branch, base, remote string, existing bool) {
	parentIdentity := ""
	if parent != "" {
		var err error
		parentIdentity, err = lifecycleRuntime(c.Request.Context()).SessionIdentity(parent)
		if err != nil || parentIdentity == "" {
			lifecycleError(c, context.Canceled)
			return
		}
	}
	o, ok := a.waitSessionLifecycle(c, "create", "", life.Intent{Name: name, Dir: dir, Parent: parent, ParentIdentity: parentIdentity, Worktree: true, Branch: branch, Base: base, Remote: remote, Existing: existing})
	if !ok {
		return
	}
	prepared, err := life.Result[lifecycleWorkspace](o, "workspace")
	if err != nil {
		lifecycleError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"name": o.ResourceID, "data": gin.H{"session": o.ResourceID, "label": name, "parent": parent, "path": prepared.Path, "branch": prepared.Branch, "base": prepared.Base}})
}
