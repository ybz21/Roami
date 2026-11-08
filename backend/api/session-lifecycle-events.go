package api

import (
	"fmt"
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// Journal cursors survive server restarts; clients always re-read the authoritative snapshot.
func (a *API) LifecycleEvents(c *gin.Context) {
	if a.Lifecycle == nil {
		lifecycleError(c, fmt.Errorf("unavailable"))
		return
	}
	flusher, ok := c.Writer.(http.Flusher)
	if !ok {
		return
	}
	c.Header("Content-Type", "text/event-stream")
	c.Header("X-Accel-Buffering", "no")
	c.Header("Cache-Control", "no-store")
	var previous int64 = -1
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	heartbeat := time.NewTicker(20 * time.Second)
	defer heartbeat.Stop()
	for {
		var cursor int64
		if err := a.Lifecycle.DB.QueryRow(`SELECT coalesce(max(cursor),0) FROM session_lifecycle_events`).Scan(&cursor); err != nil {
			return
		}
		if cursor != previous {
			fmt.Fprintf(c.Writer, "id: %d\ndata: %d\n\n", cursor, cursor)
			flusher.Flush()
			previous = cursor
		}
		select {
		case <-c.Request.Context().Done():
			return
		case <-ticker.C:
		case <-heartbeat.C:
			fmt.Fprint(c.Writer, ": heartbeat\n\n")
			flusher.Flush()
		}
	}
}
