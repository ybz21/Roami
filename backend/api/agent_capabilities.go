package api

import (
	"embed"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"sync"

	"github.com/gin-gonic/gin"
	"ttmux-web/config"
)

//go:embed prompts/agent-capabilities.md
var defaultAgentCapabilities embed.FS

const agentCapabilitiesFile = "agent-capabilities.md"

var agentCapabilitiesMu sync.Mutex

func agentCapabilitiesPath() string {
	return filepath.Join(config.Home(), agentCapabilitiesFile)
}

func readAgentCapabilities() (string, error) {
	agentCapabilitiesMu.Lock()
	defer agentCapabilitiesMu.Unlock()
	path := agentCapabilitiesPath()
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		if err = os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			return "", err
		}
		data, err = defaultAgentCapabilities.ReadFile("prompts/" + agentCapabilitiesFile)
		if err != nil {
			return "", err
		}
		f, createErr := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if errors.Is(createErr, os.ErrExist) {
			data, err = os.ReadFile(path)
		} else if createErr != nil {
			return "", createErr
		} else {
			_, err = f.Write(data)
			if closeErr := f.Close(); err == nil {
				err = closeErr
			}
		}
	}
	return string(data), err
}

func (a *API) AgentCapabilities(c *gin.Context) {
	content, err := readAgentCapabilities()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "CAPABILITIES_READ_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"content": content}})
}
