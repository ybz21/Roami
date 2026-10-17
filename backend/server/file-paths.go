package server

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"ttmux-web/api"
)

// Gin catch-all routes conflict with /file/raw and /file/serve, so aliases use the fallback.
func serveFilePath(c *gin.Context, authenticate gin.HandlerFunc, h *api.API) bool {
	if (c.Request.Method != http.MethodGet && c.Request.Method != http.MethodHead) ||
		!strings.HasPrefix(c.Request.URL.Path, "/api/file/") {
		return false
	}
	authenticate(c)
	if !c.IsAborted() {
		c.Header("Cache-Control", "no-store")
		h.FilePath(c)
	}
	return true
}
