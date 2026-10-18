package server

import (
	"net/http"
	"sync"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/backend/agentproxy"
	"github.com/ybz21/Roami/backend/config"
	"github.com/ybz21/Roami/internal/agentruntime"
)

func mountAgentRuntime(g *gin.RouterGroup, cfg Config) {
	var mu sync.Mutex
	var handler http.Handler
	forward := func(c *gin.Context) {
		mu.Lock()
		if handler == nil {
			paths, err := agentruntime.Resolve(config.Home(), cfg.DataDir)
			if err != nil {
				mu.Unlock()
				c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "AGENT_RUNTIME_UNAVAILABLE"}})
				return
			}
			handler = agentproxy.Proxy(paths.Socket)
		}
		h := handler
		mu.Unlock()
		h.ServeHTTP(c.Writer, c.Request)
	}
	for _, route := range []struct{ method, path string }{
		{"GET", "/agent/capabilities"}, {"PUT", "/agent/capabilities"}, {"POST", "/agent/main-conversation"}, {"GET", "/agent/status"}, {"GET", "/agent/conversations"}, {"POST", "/agent/conversations"},
		{"POST", "/agent/attachments"},
		{"DELETE", "/agent/attachments/:attachment"},
		{"GET", "/agent/model-settings"}, {"PUT", "/agent/model-settings"}, {"GET", "/agent/models"}, {"POST", "/agent/models"},
		{"GET", "/agent/conversations/:cid/messages"}, {"POST", "/agent/conversations/:cid/messages"},
		{"GET", "/agent/conversations/:cid/events"}, {"POST", "/agent/conversations/:cid/fork"},
		{"GET", "/agent/conversations/:cid/context"}, {"GET", "/agent/conversations/:cid/context/snapshots/:snapshot"},
		{"POST", "/agent/conversations/:cid/compact"}, {"GET", "/agent/conversations/:cid/compactions/:operation"},
		{"POST", "/agent/conversations/:cid/compactions/:operation/cancel"}, {"POST", "/agent/conversations/:cid/read"},
		{"GET", "/agent/notification-deliveries"},
		{"GET", "/agent/notification-preferences"}, {"PUT", "/agent/notification-preferences"},
		{"GET", "/agent/reminders"}, {"POST", "/agent/reminders"}, {"DELETE", "/agent/reminders/:reminder"},
		{"GET", "/agent/notifications"}, {"GET", "/agent/tasks/:task"}, {"GET", "/agent/tasks"}, {"POST", "/agent/tasks"},
		{"GET", "/agent/artifacts"}, {"GET", "/agent/artifacts/:artifact"}, {"GET", "/agent/artifacts/:artifact/content"}, {"DELETE", "/agent/artifacts/:artifact"},
		{"POST", "/agent/tasks/:task/steer"}, {"GET", "/agent/tasks/:task/steering/:operation"},
		{"POST", "/agent/tasks/:task/cancel"}, {"POST", "/agent/tasks/:task/verify"},
		{"GET", "/agent/tasks/:task/resources"}, {"GET", "/agent/resources/:resource"},
		{"POST", "/agent/resources/:resource/pause"}, {"POST", "/agent/resources/:resource/resume"},
		{"GET", "/agent/memories/:memory"}, {"GET", "/agent/memories"}, {"POST", "/agent/memories"}, {"DELETE", "/agent/memories/:memory"},
		{"POST", "/agent/memories/:memory/confirm"},
		{"GET", "/agent/memories/:memory/sources"},
	} {
		g.Handle(route.method, route.path, forward)
	}
}
