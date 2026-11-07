package api

import (
	"encoding/json"
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/memguard"
)

func (a *API) MemoryCompression(c *gin.Context) { c.JSON(http.StatusOK, memguard.Compression()) }

func (a *API) MemorySetupScript(c *gin.Context) {
	c.Header("Content-Disposition", `attachment; filename="roami-zram-setup.sh"`)
	c.Header("Cache-Control", "no-store")
	c.Data(http.StatusOK, "text/x-shellscript; charset=utf-8", memguard.CompressionSetup)
}

func (a *API) SessionReclaim(c *gin.Context) { a.recoverSessionMemory(c, "reclaim") }
func (a *API) SessionCompact(c *gin.Context) { a.recoverSessionMemory(c, "compact") }

func (a *API) recoverSessionMemory(c *gin.Context, command string) {
	out, err := a.TT.RunCtx(c.Request.Context(), command, c.Param("name"), "--json")
	if err != nil {
		code := "MEMORY_RECOVERY_FAILED"
		diagnostic := out + "\n" + err.Error()
		for _, known := range []string{"MEMORY_COMPACT_DEFERRED", "MEMORY_COMPACT_UNSUPPORTED", "SESSION_TARGET_NOT_FOUND", "SESSION_TARGET_AMBIGUOUS"} {
			if strings.Contains(diagnostic, known) {
				code = known
				break
			}
		}
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": code}})
		return
	}
	var state any
	if json.Unmarshal([]byte(out), &state) != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"code": "MEMORY_RECOVERY_FAILED"}})
		return
	}
	c.JSON(http.StatusOK, state)
}
