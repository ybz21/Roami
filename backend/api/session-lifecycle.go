package api

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/id"
	life "github.com/ybz21/Roami/internal/sessionlifecycle"
	"github.com/ybz21/Roami/internal/tmuxruntime"
)

func lifecycleID() string { var b [16]byte; _, _ = rand.Read(b[:]); return hex.EncodeToString(b[:]) }

func lifecycleError(c *gin.Context, err error) {
	code := "LIFECYCLE_UNAVAILABLE"
	status := http.StatusServiceUnavailable
	switch {
	case errors.Is(err, life.ErrConflict), errors.Is(err, life.ErrRequestKey):
		code = err.Error()
		status = http.StatusConflict
	case errors.Is(err, sql.ErrNoRows):
		code = "LIFECYCLE_NOT_FOUND"
		status = http.StatusNotFound
	default:
		if strings.HasPrefix(err.Error(), "LIFECYCLE_") {
			code = err.Error()
			status = http.StatusConflict
		}
	}
	c.JSON(status, gin.H{"error": gin.H{"code": code}})
}

func (a *API) LifecycleAccept(c *gin.Context) {
	if a.Lifecycle == nil {
		lifecycleError(c, fmt.Errorf("unavailable"))
		return
	}
	var b struct {
		Kind       string      `json:"kind"`
		RequestKey string      `json:"requestKey"`
		ResourceID string      `json:"resourceId"`
		Intent     life.Intent `json:"intent"`
	}
	if err := c.ShouldBindJSON(&b); err != nil || len(b.RequestKey) < 8 || len(b.RequestKey) > 200 || (b.Kind != "create" && b.Kind != "close") {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	if b.Kind == "create" {
		if b.Intent.Dir == "" {
			b.Intent.Dir, _ = os.UserHomeDir()
		}
		if !filepath.IsAbs(b.Intent.Dir) || strings.HasPrefix(b.Intent.Parent, "native:") {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
			return
		}
		b.Intent.Dir = filepath.Clean(b.Intent.Dir)
		if b.Intent.Parent != "" {
			if !id.Valid(b.Intent.Parent) {
				c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
				return
			}
			if _, err := a.Lifecycle.ByKey(b.RequestKey); errors.Is(err, sql.ErrNoRows) {
				identity, e := lifecycleRuntime(c.Request.Context()).SessionIdentity(b.Intent.Parent)
				if e != nil || identity == "" {
					lifecycleError(c, fmt.Errorf("LIFECYCLE_PARENT_UNAVAILABLE"))
					return
				}
				b.Intent.ParentIdentity = identity
			}
		}
		if b.Intent.Launch != nil && len(b.Intent.Launch.Command) > 8192 {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
			return
		}
		b.ResourceID = id.NewAt(time.Now())
	} else {
		if !id.Valid(b.ResourceID) || (b.Intent.Mode != "keep" && b.Intent.Mode != "discard" && b.Intent.Mode != "merge") {
			c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
			return
		}
		if b.Intent.Mode != "keep" && (b.Intent.Snapshot == "" || !filepath.IsAbs(b.Intent.Path)) {
			lifecycleError(c, fmt.Errorf("LIFECYCLE_CONFIRM_AGAIN"))
			return
		}
		if b.Intent.SessionIdentity == "" {
			lifecycleError(c, fmt.Errorf("LIFECYCLE_CONFIRM_AGAIN"))
			return
		}
	}
	operation, err := a.Lifecycle.Accept(lifecycleID(), b.ResourceID, b.RequestKey, b.Kind, b.Intent)
	if err != nil {
		lifecycleError(c, err)
		return
	}
	c.JSON(http.StatusAccepted, gin.H{"data": operation})
}

func (a *API) LifecycleList(c *gin.Context) {
	if a.Lifecycle == nil {
		lifecycleError(c, fmt.Errorf("unavailable"))
		return
	}
	if key := c.Query("requestKey"); key != "" {
		o, err := a.Lifecycle.ByKey(key)
		if err != nil {
			lifecycleError(c, err)
			return
		}
		c.JSON(http.StatusOK, gin.H{"data": o})
		return
	}
	operations, err := a.Lifecycle.List()
	if err != nil {
		lifecycleError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": operations})
}

func (a *API) LifecycleGet(c *gin.Context) {
	if a.Lifecycle == nil {
		lifecycleError(c, fmt.Errorf("unavailable"))
		return
	}
	o, err := a.Lifecycle.Get(c.Param("operation"))
	if err != nil {
		lifecycleError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": o})
}

func (a *API) LifecycleAction(c *gin.Context) {
	if a.Lifecycle == nil {
		lifecycleError(c, fmt.Errorf("unavailable"))
		return
	}
	var b struct {
		Revision   int64  `json:"revision"`
		RequestKey string `json:"requestKey"`
	}
	if c.ShouldBindJSON(&b) != nil || len(b.RequestKey) < 8 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return
	}
	action := c.Param("action")
	o, err := a.Lifecycle.Action(c.Param("operation"), b.RequestKey, action, b.Revision, func(o *life.Operation) error {
		if o.Terminal() {
			return life.ErrConflict
		}
		switch action {
		case "retry":
			if o.State != "attention" || o.ErrorCode == "LIFECYCLE_RESULT_UNKNOWN" {
				return life.ErrConflict
			}
			o.State = "queued"
			o.ErrorCode = ""
			o.ErrorDetail = ""
		case "cancel":
			if o.Kind != "create" {
				return life.ErrConflict
			}
			o.CancelRequested = true
			if o.State == "attention" {
				o.State = "queued"
			}
		case "retain":
			if o.Kind != "close" || o.State != "attention" || o.Has("remove") {
				return life.ErrConflict
			}
			o.Intent.Mode = "keep"
			o.State = "queued"
			o.ErrorCode = ""
			o.ErrorDetail = ""
		case "retain-branch":
			if o.Kind != "close" || o.State != "attention" || !o.Has("remove") {
				return life.ErrConflict
			}
			o.Intent.KeepBranch = true
			o.State = "queued"
			o.ErrorCode = ""
			o.ErrorDetail = ""
		default:
			return fmt.Errorf("LIFECYCLE_ACTION_INVALID")
		}
		return nil
	})
	if err != nil {
		lifecycleError(c, err)
		return
	}
	c.JSON(http.StatusAccepted, gin.H{"data": o})
}

func (a *API) StartSessionLifecycle(ctx context.Context) func() {
	if a.Lifecycle == nil {
		return func() {}
	}
	if ctx == nil {
		ctx = context.Background()
	}
	a.lifecycleContext = ctx
	worker := &life.Worker{Store: a.Lifecycle, Steps: a.lifecycleSteps}
	return worker.Start(ctx)
}

func lifecycleRuntime(ctx context.Context) runtime.Runtime {
	rt := runtime.New()
	rt.Context = ctx
	return rt
}

func lifecycleFailure(err error) error {
	if err == nil {
		return nil
	}
	code := "LIFECYCLE_STEP_FAILED"
	if strings.HasPrefix(err.Error(), "LIFECYCLE_") {
		code = strings.SplitN(err.Error(), ":", 2)[0]
	}
	return &life.Failure{Code: code, Err: err}
}
