package api

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/okr"
	storage "github.com/ybz21/Roami/internal/storage"
)

func openProjectOKR(dataDir string) *okr.Store {
	paths, err := storage.ResolvePaths("", dataDir)
	if err == nil {
		var store *okr.Store
		store, err = okr.Open(paths)
		if err == nil {
			return store
		}
	}
	log.Printf("project OKR storage unavailable: %v", err)
	return nil
}

func okrError(c *gin.Context, err error) {
	status, code := http.StatusInternalServerError, "OKR_STORAGE_FAILED"
	switch {
	case errors.Is(err, okr.ErrInvalid):
		status, code = http.StatusBadRequest, "OKR_INVALID"
	case errors.Is(err, okr.ErrConflict):
		status, code = http.StatusConflict, "OKR_CONFLICT"
	case errors.Is(err, okr.ErrNotFound):
		status, code = http.StatusNotFound, "OKR_NOT_FOUND"
	case errors.Is(err, okr.ErrSource), errors.Is(err, context.DeadlineExceeded):
		status, code = http.StatusBadGateway, "OKR_SOURCE_FAILED"
	}
	if status == http.StatusInternalServerError {
		log.Printf("project OKR request: %v", err)
	}
	c.JSON(status, gin.H{"error": code})
}

func (a *API) okrProject(c *gin.Context) (string, bool) {
	if a.Projects != nil {
		if project, ok := a.Projects.Entry(c.Param("key")); ok {
			if a.ProjectOKR == nil {
				c.JSON(http.StatusServiceUnavailable, gin.H{"error": "OKR_UNAVAILABLE"})
				return "", false
			}
			return project.ID, true
		}
	}
	c.JSON(http.StatusNotFound, gin.H{"error": "PROJECT_NOT_FOUND"})
	return "", false
}

// Reject omitted/null revisions, history replacement, and trailing JSON before any mutation.
func decodeOKR(c *gin.Context, target any) bool {
	b, err := io.ReadAll(http.MaxBytesReader(c.Writer, c.Request.Body, 1<<20))
	var envelope struct {
		Revision *int64 `json:"revision"`
	}
	if err != nil || json.Unmarshal(b, &envelope) != nil || envelope.Revision == nil || *envelope.Revision < 0 {
		okrError(c, okr.ErrInvalid)
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(b))
	decoder.DisallowUnknownFields()
	if decoder.Decode(target) != nil {
		okrError(c, okr.ErrInvalid)
		return false
	}
	return true
}

func (a *API) ProjectOKRGet(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	w, err := a.ProjectOKR.Get(projectID)
	if err != nil {
		okrError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": w})
}

func (a *API) resolveOKRSwarm(ctx context.Context, key string) (string, error) {
	if key == "" {
		return "", nil
	}
	if a.Meta.OK() {
		var name string
		err := a.Meta.QueryRow(`SELECT name FROM swarms WHERE id=? OR name=? LIMIT 1`, key, key).Scan(&name)
		if errors.Is(err, sql.ErrNoRows) {
			return "", okr.ErrInvalid
		}
		if err != nil {
			return "", err
		}
		return name, nil
	}
	if a.TT == nil {
		return "", okr.ErrInvalid
	}
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	out, err := a.TT.RunCtx(ctx, "swarm", "ls", "--json")
	if err != nil {
		return "", err
	}
	var swarms []struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := json.Unmarshal([]byte(out), &swarms); err != nil {
		return "", err
	}
	for _, s := range swarms {
		if (key == s.ID || key == s.Name) && s.ID != "" {
			return s.Name, nil
		}
	}
	return "", okr.ErrInvalid
}

func (a *API) ProjectOKRSave(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	var config okr.Config
	if !decodeOKR(c, &config) {
		return
	}
	swarmName, err := a.resolveOKRSwarm(c.Request.Context(), config.Swarm)
	if err != nil {
		okrError(c, err)
		return
	}
	config.Swarm = swarmName
	w, err := a.ProjectOKR.Save(projectID, config)
	if err != nil {
		okrError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": w})
}

func (a *API) ProjectOKRObserve(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	var b struct {
		Revision int64    `json:"revision"`
		MetricID string   `json:"metricId"`
		Date     string   `json:"date"`
		Value    *float64 `json:"value"`
		Note     string   `json:"note"`
	}
	if !decodeOKR(c, &b) {
		return
	}
	if b.Value == nil {
		okrError(c, okr.ErrInvalid)
		return
	}
	w, err := a.ProjectOKR.Observe(projectID, b.Revision, b.MetricID, b.Date, *b.Value, b.Note)
	if err != nil {
		okrError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": w})
}

func (a *API) ProjectOKRCollect(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	var b struct {
		Revision int64 `json:"revision"`
	}
	if !decodeOKR(c, &b) {
		return
	}
	w, err := a.ProjectOKR.Collect(c.Request.Context(), a.projectOKRGitHub, projectID, b.Revision, false)
	if err != nil {
		okrError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": w})
}

func (a *API) ProjectOKRReview(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	var b struct {
		Revision int64  `json:"revision"`
		Summary  string `json:"summary"`
		Actions  string `json:"actions"`
	}
	if !decodeOKR(c, &b) {
		return
	}
	w, err := a.ProjectOKR.Review(projectID, b.Revision, b.Summary, b.Actions)
	if err != nil {
		okrError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": w})
}

func (a *API) ProjectOKREvidence(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	w, err := a.ProjectOKR.Evidence(projectID, c.Param("reviewID"))
	if err != nil {
		okrError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": w})
}

func (a *API) ProjectOKRCollector(ctx context.Context) {
	if a.ProjectOKR == nil {
		return
	}
	a.ProjectOKR.RunCollector(ctx, a.projectOKRGitHub, func(projectID string) bool {
		entry, ok := a.Projects.Entry(projectID)
		return ok && entry.ID == projectID
	})
}
