package api

import (
	"encoding/json"
	"io"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/agentproviders"
)

func providerError(c *gin.Context, err error) {
	code := err.Error()
	status := http.StatusInternalServerError
	switch code {
	case "INVALID_AGENT_KIND", "INVALID_MODEL_PROFILE", "INVALID_MODEL_PROTOCOL", "INVALID_MODEL_KEY", "MODEL_KEY_ENV_MISSING":
		status = http.StatusBadRequest
	case "MODEL_LIST_UNAUTHORIZED", "MODEL_LIST_UNSUPPORTED", "MODEL_LIST_FAILED":
		status = http.StatusBadGateway
	case "MODEL_PROFILE_NOT_FOUND":
		status = http.StatusNotFound
	case "MODEL_PROFILE_ACTIVE", "MODEL_PROFILE_NAME_EXISTS", "MODEL_PROFILE_LIMIT", "AGENT_CONFIG_CHANGED", "AGENT_CONFIG_INVALID", "AGENT_CONFIG_PATH_INVALID",
		"AGENT_CONFIG_INLINE_OVERRIDE", "AGENT_CONFIG_RESTORE_UNAVAILABLE", "OPENCODE_CONFIG_VERSION_UNKNOWN", "AGENT_CONFIG_RECOVERY_REQUIRED":
		status = http.StatusConflict
	}
	c.JSON(status, gin.H{"error": gin.H{"code": code}})
}

func providerBody(c *gin.Context, body any) bool {
	reader := http.MaxBytesReader(c.Writer, c.Request.Body, 64<<10)
	decoder := json.NewDecoder(reader)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(body); err != nil {
		code, status := "BAD_REQUEST", http.StatusBadRequest
		if strings.Contains(err.Error(), "request body too large") {
			code, status = "REQUEST_TOO_LARGE", http.StatusRequestEntityTooLarge
		}
		c.JSON(status, gin.H{"error": gin.H{"code": code}})
		return false
	}
	if decoder.Decode(new(any)) != io.EOF {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_REQUEST"}})
		return false
	}
	return true
}

func (a *API) AgentModelProfiles(c *gin.Context) {
	if a.AgentProviders == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "MODEL_STORE_UNAVAILABLE"}})
		return
	}
	view, err := a.AgentProviders.View(c.Request.Context(), c.Param("kind"))
	if err != nil {
		providerError(c, err)
		return
	}
	c.JSON(http.StatusOK, view)
}

func (a *API) SaveAgentModelProfile(c *gin.Context) {
	if a.AgentProviders == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "MODEL_STORE_UNAVAILABLE"}})
		return
	}
	var input agentproviders.ProfileInput
	if !providerBody(c, &input) {
		return
	}
	profile, err := a.AgentProviders.Save(c.Request.Context(), c.Param("kind"), c.Param("profile"), input)
	if err != nil {
		providerError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"profile": profile})
}

func (a *API) DeleteAgentModelProfile(c *gin.Context) {
	if a.AgentProviders == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "MODEL_STORE_UNAVAILABLE"}})
		return
	}
	if err := a.AgentProviders.Delete(c.Request.Context(), c.Param("kind"), c.Param("profile")); err != nil {
		providerError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"deleted": true})
}

func (a *API) ApplyAgentModelProfile(c *gin.Context)   { a.changeAgentModel(c, "custom") }
func (a *API) RestoreAgentModelProfile(c *gin.Context) { a.changeAgentModel(c, "restore") }

func (a *API) UseOfficialAgentModel(c *gin.Context) { a.changeAgentModel(c, "official") }

func (a *API) changeAgentModel(c *gin.Context, mode string) {
	if a.AgentProviders == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "MODEL_STORE_UNAVAILABLE"}})
		return
	}
	var body struct {
		Revision string `json:"revision"`
	}
	if !providerBody(c, &body) {
		return
	}
	var view agentproviders.View
	var err error
	if mode == "official" {
		view, err = a.AgentProviders.UseOfficial(c.Request.Context(), c.Param("kind"), body.Revision)
	} else if mode == "restore" {
		view, err = a.AgentProviders.Restore(c.Request.Context(), c.Param("kind"), body.Revision)
	} else {
		view, err = a.AgentProviders.Apply(c.Request.Context(), c.Param("kind"), c.Param("profile"), body.Revision)
	}
	if err != nil {
		providerError(c, err)
		return
	}
	c.JSON(http.StatusOK, view)
}

func (a *API) AgentModelOptions(c *gin.Context) {
	if a.AgentProviders == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "MODEL_STORE_UNAVAILABLE"}})
		return
	}
	var query agentproviders.ModelQuery
	if !providerBody(c, &query) {
		return
	}
	models, err := a.AgentProviders.ModelOptions(c.Request.Context(), c.Param("kind"), query)
	if err != nil {
		providerError(c, err)
		return
	}
	c.JSON(http.StatusOK, gin.H{"models": models})
}
