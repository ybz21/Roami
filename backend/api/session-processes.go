package api

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
)

func (a *API) SessionProcesses(c *gin.Context) {
	a.sessionProcessCommand(c, "processes", []string{c.Param("name"), "--json"})
}

func (a *API) SessionProcessStop(c *gin.Context) {
	var req struct {
		Start string `json:"start"`
		Force bool   `json:"force"`
	}
	pid, err := strconv.Atoi(c.Param("pid"))
	if err != nil || pid <= 1 || c.ShouldBindJSON(&req) != nil || req.Start == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "SESSION_PROCESS_STALE"}})
		return
	}
	args := []string{c.Param("name"), strconv.Itoa(pid), req.Start, "--json"}
	if req.Force {
		args = append(args, "--force")
	}
	a.sessionProcessCommand(c, "process-stop", args)
}

func (a *API) sessionProcessCommand(c *gin.Context, command string, args []string) {
	c.Header("Cache-Control", "no-store")
	out, err := a.TT.RunCtx(c.Request.Context(), append([]string{command}, args...)...)
	if err != nil {
		code := "SESSION_PROCESS_UNAVAILABLE"
		for _, known := range []string{"SESSION_PROCESS_STALE", "SESSION_PROCESS_PROTECTED", "SESSION_PROCESS_SHARED_PANE", "SESSION_PROCESS_STOP_FAILED"} {
			if strings.Contains(out+err.Error(), known) {
				code = known
				break
			}
		}
		c.JSON(http.StatusConflict, gin.H{"error": gin.H{"code": code}})
		return
	}
	var result any
	if json.Unmarshal([]byte(out), &result) != nil {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"code": "SESSION_PROCESS_UNAVAILABLE"}})
		return
	}
	c.JSON(http.StatusOK, result)
}
