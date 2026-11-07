package api

import (
	"net/http"
	"strings"

	"github.com/gin-gonic/gin"
)

func (a *API) SessionPause(c *gin.Context)  { a.setSessionPaused(c, true) }
func (a *API) SessionResume(c *gin.Context) { a.setSessionPaused(c, false) }

func (a *API) setSessionPaused(c *gin.Context, paused bool) {
	command := "resume"
	if paused {
		command = "pause"
	}
	_, err := a.TT.RunCtx(c.Request.Context(), command, c.Param("name"), "--json")
	if err != nil {
		code := "SESSION_PAUSE_FAILED"
		for _, known := range []string{"SESSION_PAUSE_UNAVAILABLE", "SESSION_PAUSE_SHARED_PANE", "SESSION_TARGET_NOT_FOUND", "SESSION_TARGET_AMBIGUOUS"} {
			if strings.Contains(err.Error(), known) {
				code = known
				break
			}
		}
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": code}})
		return
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"paused": paused}})
}
