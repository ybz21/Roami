package api

import (
	"context"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/agentinventory"
)

func (a *API) ProfessionalAgents(c *gin.Context) {
	rows := agentinventory.DiscoverProfessionalAgents(c.Request.Context())
	a.annotateProfessionalPresets(c.Request.Context(), rows)
	a.annotateAgentVerification(c.Request.Context(), rows)
	c.JSON(http.StatusOK, gin.H{"agents": rows})
}

func (a *API) annotateProfessionalPresets(ctx context.Context, rows []agentinventory.ProfessionalAgent) {
	if a.AgentProviders == nil {
		return
	}
	presets := a.AgentProviders.Observations(ctx)
	for i := range rows {
		if name := presets[rows[i].Kind]; name != "" {
			rows[i].ModelPreset = name
			rows[i].Quota = agentinventory.AgentQuota{State: "unknown", Reason: "provider_managed"}
		}
	}
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
	rows := []agentinventory.ProfessionalAgent{row}
	a.annotateProfessionalPresets(c.Request.Context(), rows)
	a.annotateAgentVerification(c.Request.Context(), rows)
	c.JSON(http.StatusOK, gin.H{"agent": rows[0]})
}

func (a *API) UpgradeProfessionalAgent(c *gin.Context) {
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Minute)
	defer cancel()
	row, err := agentinventory.UpgradeProfessionalAgent(ctx, c.Param("kind"))
	if err != nil {
		status := http.StatusInternalServerError
		switch err.Error() {
		case "INVALID_AGENT_KIND":
			status = http.StatusBadRequest
		case "AGENT_NOT_INSTALLED", "AGENT_UPGRADE_UNSUPPORTED", "AGENT_MAINTENANCE_BUSY":
			status = http.StatusConflict
		}
		c.JSON(status, gin.H{"error": gin.H{"code": err.Error()}})
		return
	}
	rows := []agentinventory.ProfessionalAgent{row}
	a.annotateProfessionalPresets(c.Request.Context(), rows)
	a.annotateAgentVerification(c.Request.Context(), rows)
	c.JSON(http.StatusOK, gin.H{"agent": rows[0]})
}
