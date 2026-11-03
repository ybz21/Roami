package api

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"regexp"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/ybz21/Roami/internal/agentruntime"
)

var managedSwarmID = regexp.MustCompile(`^sw-[a-f0-9]{32}$`)

func (a *API) managedSwarms(ctx context.Context, id string) (any, error) {
	socket := a.AgentSocket
	if socket == "" {
		return nil, fmt.Errorf("AGENT_RUNTIME_UNAVAILABLE")
	}
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	path := "/v1/swarms"
	if id != "" {
		path += "/" + url.PathEscape(id)
	}
	req, err := http.NewRequestWithContext(ctx, "GET", "http://roami-agent"+path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-Roami-Owner", "local")
	transport := agentruntime.Transport(socket)
	defer transport.CloseIdleConnections()
	response, err := (&http.Client{Transport: transport}).Do(req)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("AGENT_RUNTIME_UNAVAILABLE")
	}
	var body struct {
		Data any `json:"data"`
	}
	err = json.NewDecoder(io.LimitReader(response.Body, 8<<20)).Decode(&body)
	return body.Data, err
}

func managedProjection(value map[string]any) map[string]any {
	works, _ := value["work"].([]any)
	members := []any{}
	alive := 0
	for _, raw := range works {
		work, _ := raw.(map[string]any)
		state, _ := work["state"].(string)
		switch state {
		case "succeeded":
			state = "done"
		case "queued", "preparing", "verifying":
			state = "running"
		case "blocked", "waiting_user":
			state = "waiting"
		}
		if state == "running" || state == "waiting" {
			alive++
		}
		session := ""
		if attempt, ok := work["attempt"].(map[string]any); ok {
			session, _ = attempt["sessionId"].(string)
		}
		members = append(members, map[string]any{"name": work["member_name"], "task": work["title"], "kind": work["executor"], "type": "agent", "role": "member", "session": session, "status": state, "taskId": work["task_id"], "done": 0})
	}
	state := value["state"]
	if state == "blocked" || state == "review" {
		state = "integrating"
	}
	if value["archived"] == true {
		state = "archived"
	}
	dir := ""
	if target, ok := value["target"].(map[string]any); ok {
		dir, _ = target["directory"].(string)
	}
	return map[string]any{"id": value["id"], "name": value["id"], "label": value["name"], "goal": value["goal"], "engine": "roami_v2", "status": state, "dir": dir, "supervisor": "", "mainConversationId": value["mainConversationId"], "total": len(works), "alive": alive, "pending": 0, "members": members, "pending_members": []any{}}
}

func (a *API) managedSwarmStatus(c *gin.Context) bool {
	if !managedSwarmID.MatchString(c.Param("n")) {
		return false
	}
	value, err := a.managedSwarms(c.Request.Context(), c.Param("n"))
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": gin.H{"code": "AGENT_RUNTIME_UNAVAILABLE"}})
		return true
	}
	snapshot, ok := value.(map[string]any)
	if !ok {
		c.JSON(http.StatusBadGateway, gin.H{"error": gin.H{"code": "INVALID_SWARM_SNAPSHOT"}})
		return true
	}
	projection := managedProjection(snapshot)
	projection["pending"] = []any{}
	projection["done_marked"] = []any{}
	c.JSON(http.StatusOK, projection)
	return true
}
