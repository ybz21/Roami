package api

import (
	"crypto/sha256"
	"embed"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/config"
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
	if err == nil && isShippedAgentCapabilities(data) {
		data, err = defaultAgentCapabilities.ReadFile("prompts/" + agentCapabilitiesFile)
		if err == nil {
			err = replaceAgentCapabilities(path, data)
		}
	}
	return string(data), err
}

// Match shipped defaults exactly so upgrades never overwrite an edited guide.
func isShippedAgentCapabilities(data []byte) bool {
	content := strings.TrimSpace(strings.ReplaceAll(string(data), "\r\n", "\n"))
	switch fmt.Sprintf("%x", sha256.Sum256([]byte(content))) {
	case "0d50a9e28f927ed484a75c9fe898ec72d47823574f2f71b1f4f8d92f9ee66786", // #317
		"8774efb02f7ffef268c3cfa6cdd51a5b2eb8af9be5969ee529302e6095894dda", // #328
		"a7b402f283e8182fedbd330dd5ca775ad9d210985a148f364cdbbc3e19af6aec", // #399
		"731ca3553ff6cfedc7f5560ae54351c362a388a7d4913adfeda1478b03dea849": // #403
		return true
	}
	return false
}

func replaceAgentCapabilities(path string, data []byte) error {
	f, err := os.CreateTemp(filepath.Dir(path), ".agent-capabilities-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	_, err = f.Write(data)
	if closeErr := f.Close(); err == nil {
		err = closeErr
	}
	if err != nil {
		return err
	}
	return os.Rename(f.Name(), path)
}

func (a *API) AgentCapabilities(c *gin.Context) {
	content, err := readAgentCapabilities()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": gin.H{"code": "CAPABILITIES_READ_ERROR", "message": err.Error()}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"content": content}})
}
