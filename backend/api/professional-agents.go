package api

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/agentinventory"
)

func (a *API) ProfessionalAgents(c *gin.Context) {
	c.JSON(http.StatusOK, gin.H{"agents": agentinventory.DiscoverProfessionalAgents(c.Request.Context())})
}

func (a *API) InstallProfessionalAgent(c *gin.Context) {
	args, err := agentinventory.ProfessionalInstallArgs(c.Param("kind"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "INVALID_AGENT_KIND"}})
		return
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Minute)
	defer cancel()
	if err := agentinventory.InstallProfessionalAgent(ctx, args); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "AGENT_INSTALL_FAILED"}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"installed": true})
}

func (a *API) CheckProfessionalAgent(c *gin.Context) {
	row, err := agentinventory.CheckProfessionalAgent(c.Request.Context(), c.Param("kind"))
	if err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "INVALID_AGENT_KIND"}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"agent": row})
}
