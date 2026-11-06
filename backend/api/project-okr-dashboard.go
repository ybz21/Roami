package api

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/okr"
)

func (a *API) ProjectOKRDashboard(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	bundle, workspace, err := a.ProjectOKR.Dashboard(projectID)
	if err != nil {
		okrError(c, err)
		return
	}
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"projectId": projectID, "revision": workspace.Revision, "digest": bundle.Digest, "metricIds": bundle.MetricIDs, "libraries": bundle.Libraries}})
}

func (a *API) ProjectOKRDashboardDocument(c *gin.Context) {
	projectID, ok := a.okrProject(c)
	if !ok {
		return
	}
	bundle, _, err := a.ProjectOKR.Dashboard(projectID)
	if err != nil {
		okrError(c, err)
		return
	}
	if c.Query("digest") != bundle.Digest {
		okrError(c, okr.ErrConflict)
		return
	}
	document, err := bundle.Document(c.Query("nonce"))
	if err != nil {
		okrError(c, err)
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline' data:; style-src 'unsafe-inline' data:; img-src data: blob:; font-src data:; connect-src 'none'; frame-src 'none'; object-src 'none'; media-src 'none'; worker-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'; sandbox allow-scripts")
	c.Header("X-Content-Type-Options", "nosniff")
	c.Header("Referrer-Policy", "no-referrer")
	c.Data(http.StatusOK, "text/html; charset=utf-8", []byte(document))
}
