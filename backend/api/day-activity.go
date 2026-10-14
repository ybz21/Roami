package api

import (
	"github.com/gin-gonic/gin"
	"net/http"
	"strconv"
)

func (a *API) DayActivity(c *gin.Context) {
	from, fromErr := strconv.ParseInt(c.Query("from"), 10, 64)
	to, toErr := strconv.ParseInt(c.Query("to"), 10, 64)
	if fromErr != nil || toErr != nil || from < 0 || to <= from || to-from > 48*60*60 {
		c.JSON(http.StatusBadRequest, gin.H{"error": gin.H{"code": "BAD_DATE_RANGE"}})
		return
	}
	if a.GitFootprints == nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "HISTORY_UNAVAILABLE"}})
		return
	}
	commits, err := a.GitFootprints.Day(c.Request.Context(), from, to)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "HISTORY_UNAVAILABLE"}})
		return
	}
	events, failed := a.Footprints.Snapshot()
	usage := []AIFootprint{}
	for _, event := range events {
		if event.At >= from && event.At < to {
			usage = append(usage, event)
		}
	}
	c.JSON(http.StatusOK, gin.H{"data": gin.H{"commits": commits, "usage": usage, "recordingFailed": failed}})
}
