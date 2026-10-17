package server

import (
	"net/http"
	"sync"

	"github.com/gin-gonic/gin"
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
			handler = agentruntime.Proxy(paths.Socket)
		}
		h := handler
		mu.Unlock()
		h.ServeHTTP(c.Writer, c.Request)
	}
	for _, route := range []struct{ method, path string }{
		{"GET", "/agent/status"}, {"GET", "/agent/conversations"}, {"POST", "/agent/conversations"},
		{"GET", "/agent/conversations/:cid/messages"}, {"POST", "/agent/conversations/:cid/messages"},
		{"GET", "/agent/conversations/:cid/events"}, {"POST", "/agent/conversations/:cid/fork"},
		{"GET", "/agent/conversations/:cid/context"}, {"GET", "/agent/conversations/:cid/context/snapshots/:snapshot"},
		{"POST", "/agent/conversations/:cid/compact"}, {"GET", "/agent/conversations/:cid/compactions/:operation"},
		{"POST", "/agent/conversations/:cid/compactions/:operation/cancel"}, {"POST", "/agent/conversations/:cid/read"},
		{"GET", "/agent/notifications"}, {"GET", "/agent/tasks"}, {"POST", "/agent/tasks"},
		{"POST", "/agent/tasks/:task/cancel"}, {"POST", "/agent/tasks/:task/verify"},
		{"GET", "/agent/memories/:memory"}, {"GET", "/agent/memories"}, {"POST", "/agent/memories"}, {"DELETE", "/agent/memories/:memory"},
	} {
		g.Handle(route.method, route.path, forward)
	}
}
