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
		{"GET", "/agent/model-gateway/plugins/packages"}, {"POST", "/agent/model-gateway/plugins/import"}, {"POST", "/agent/model-gateway/plugins/inspect"}, {"POST", "/agent/model-gateway/plugins/sources"}, {"GET", "/agent/model-gateway/plugins/sources/:source/info"}, {"POST", "/agent/model-gateway/plugins/sources/:source/options"}, {"POST", "/agent/model-gateway/plugins/sources/:source/auth"}, {"GET", "/agent/model-gateway/plugins/sources/:source/auth-jobs/:job"}, {"DELETE", "/agent/model-gateway/plugins/sources/:source/auth-jobs/:job"},
		{"GET", "/agent/model-gateway/access-keys"}, {"POST", "/agent/model-gateway/access-keys"}, {"PATCH", "/agent/model-gateway/access-keys/:id"}, {"DELETE", "/agent/model-gateway/access-keys/:id"}, {"POST", "/agent/model-gateway/access-keys/:id/rotate"},
		{"GET", "/agent/model-gateway/access-key"}, {"PUT", "/agent/model-gateway/access-key"}, {"DELETE", "/agent/model-gateway/access-key"},
		{"POST", "/agent/model-gateway/monitor/check"}, {"GET", "/agent/model-gateway/monitor"}, {"GET", "/agent/model-gateway/settings/sources/:source"}, {"PUT", "/agent/model-gateway/settings/sources/:source"},
		{"GET", "/agent/model-gateway/settings"}, {"PUT", "/agent/model-gateway/settings"},
		{"GET", "/agent/model-gateway/catalog/routing"}, {"GET", "/agent/model-gateway/catalog"}, {"PUT", "/agent/model-gateway/catalog"}, {"POST", "/agent/model-gateway/catalog/apply"},
		{"POST", "/agent/model-gateway/catalog/discover"}, {"POST", "/agent/model-gateway/catalog/roles"}, {"POST", "/agent/model-gateway/catalog/source-models"},
		{"GET", "/agent/model-gateway/catalog/local-sources"}, {"POST", "/agent/model-gateway/catalog/local-sources"},
		{"GET", "/agent/model-gateway/usage"}, {"PUT", "/agent/model-gateway/calls/:call"},
		{"GET", "/agent/capability-markets"}, {"PUT", "/agent/capability-markets"},
		{"GET", "/agent/capability-markets/:source/search"}, {"POST", "/agent/capability-markets/preview"},
		{"POST", "/agent/capability-markets/prepare"}, {"POST", "/agent/capability-markets/install"},
		{"PUT", "/agent/capability-imports/:kind/:name"}, {"DELETE", "/agent/capability-imports/:kind/:name"}, {"POST", "/agent/capability-imports/mcp/:name/connect"}, {"GET", "/agent/capability-imports"}, {"POST", "/agent/capability-imports/:kind"}, {"GET", "/agent/capability-settings"}, {"PUT", "/agent/capability-settings"}, {"POST", "/agent/main-conversation"}, {"GET", "/agent/swarms"}, {"POST", "/agent/swarms"}, {"GET", "/agent/swarms/:sid"}, {"GET", "/agent/swarms/:sid/inbox"}, {"GET", "/agent/swarms/:sid/members"}, {"POST", "/agent/swarms/:sid/members"}, {"GET", "/agent/swarms/:sid/members/:member"}, {"POST", "/agent/swarms/:sid/plan"}, {"POST", "/agent/swarms/:sid/dependencies"}, {"POST", "/agent/swarms/:sid/control"}, {"POST", "/agent/swarms/:sid/messages"}, {"GET", "/agent/swarms/:sid/events"}, {"GET", "/agent/status"}, {"GET", "/agent/conversations"}, {"POST", "/agent/conversations"},
		{"POST", "/agent/attachments"},
		{"PUT", "/agent/swarms/:sid/memory"},
		{"GET", "/agent/traces"},
		{"GET", "/agent/improvement/cycles"}, {"GET", "/agent/improvement/cycles/:cycle_id"},
		{"GET", "/agent/improvement"}, {"PUT", "/agent/improvement/preferences"},
		{"GET", "/agent/improvement/cases"},
		{"POST", "/agent/improvement/machines"}, {"POST", "/agent/improvement/requests"},
		{"POST", "/agent/improvement/requests/:request_id/cancel"},
		{"POST", "/agent/improvement/releases"}, {"POST", "/agent/improvement/rollback"},
		{"POST", "/agent/improvement/prepare"},
		{"GET", "/agent/improvement/research"},
		{"PUT", "/agent/improvement/research"}, {"POST", "/agent/improvement/preview"},
		{"PUT", "/agent/improvement/pipeline/settings"}, {"POST", "/agent/improvement/pipeline/requests"},
		{"GET", "/agent/improvement/pipeline/runs/:run_id"},
		{"GET", "/agent/improvement/pipeline/runs/:run_id/results"},
		{"GET", "/agent/improvement/pipeline/runs/:run_id/artifacts/:artifact_id"},
		{"POST", "/agent/improvement/pipeline/runs/:run_id/resume"}, {"POST", "/agent/improvement/pipeline/runs/:run_id/publish"},
		{"POST", "/agent/improvement/research/:action_id/resume"},
		{"GET", "/agent/conversations/:cid/identity"}, {"GET", "/agent/conversations/:cid/debug"}, {"GET", "/agent/conversations/:cid/debug/trace"},
		{"DELETE", "/agent/attachments/:attachment"},
		{"GET", "/agent/model-settings"}, {"PUT", "/agent/model-settings"}, {"POST", "/agent/model-settings/verify"}, {"GET", "/agent/model-usage"}, {"GET", "/agent/models"}, {"POST", "/agent/models"},
		{"GET", "/agent/conversations/:cid/messages/:mid"},
		{"GET", "/agent/conversations/:cid/activities/:aid"}, {"GET", "/agent/conversations/:cid/messages"}, {"POST", "/agent/conversations/:cid/messages"}, {"POST", "/agent/conversations/:cid/wake"},
		{"GET", "/agent/conversations/:cid/events"}, {"POST", "/agent/conversations/:cid/fork"},
		{"GET", "/agent/conversations/:cid/context"}, {"GET", "/agent/conversations/:cid/context/snapshots/:snapshot"},
		{"POST", "/agent/conversations/:cid/compact"}, {"GET", "/agent/conversations/:cid/compactions/:operation"},
		{"POST", "/agent/conversations/:cid/compactions/:operation/cancel"}, {"POST", "/agent/conversations/:cid/read"},
		{"GET", "/agent/notification-deliveries"},
		{"GET", "/agent/notification-preferences"}, {"PUT", "/agent/notification-preferences"},
		{"GET", "/agent/reminders"}, {"POST", "/agent/reminders"}, {"DELETE", "/agent/reminders/:reminder"},
		{"GET", "/agent/notifications/summary"}, {"POST", "/agent/notifications/read"},
		{"GET", "/agent/notification-list"}, {"GET", "/agent/task-list"},
		{"GET", "/agent/notifications"}, {"GET", "/agent/tasks/:task"}, {"GET", "/agent/tasks"}, {"POST", "/agent/tasks"},
		{"GET", "/agent/artifacts"}, {"GET", "/agent/artifacts/:artifact"}, {"GET", "/agent/artifacts/:artifact/content"}, {"DELETE", "/agent/artifacts/:artifact"},
		{"POST", "/agent/tasks/:task/steer"}, {"GET", "/agent/tasks/:task/steering/:operation"},
		{"GET", "/agent/native-sessions"}, {"GET", "/agent/native-sessions/:session"}, {"PATCH", "/agent/native-sessions/:session"}, {"GET", "/agent/native-sessions/:session/conversation"}, {"GET", "/agent/native-sessions/:session/events"},
		{"POST", "/agent/tasks/:task/close-session"},
		{"POST", "/agent/tasks/:task/cancel"}, {"POST", "/agent/tasks/:task/verify"},
		{"GET", "/agent/tasks/:task/activities"}, {"GET", "/agent/tasks/:task/activities/:activity"}, {"GET", "/agent/tasks/:task/conversation"},
		{"GET", "/agent/tasks/:task/resources"}, {"GET", "/agent/resources/:resource"},
		{"POST", "/agent/resources/:resource/pause"}, {"POST", "/agent/resources/:resource/resume"},
		{"GET", "/agent/memories/:memory"}, {"GET", "/agent/memories"}, {"POST", "/agent/memories"}, {"DELETE", "/agent/memories/:memory"},
		{"POST", "/agent/memories/:memory/confirm"},
		{"GET", "/agent/memories/:memory/sources"}, {"GET", "/agent/memories/:memory/detail"}, {"GET", "/agent/memories/:memory/history"},
	} {
		g.Handle(route.method, route.path, forward)
	}
}
