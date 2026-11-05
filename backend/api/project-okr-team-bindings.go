package api

import (
	"context"
	"encoding/json"
	"time"

	"github.com/ybz21/Roami/backend/okr"
)

// A role references an existing runtime member; it never creates or rehomes an instance.
func (a *API) validateOKRRoleBindings(ctx context.Context, projectID string, config *okr.Config) error {
	if config.Team == nil {
		return nil
	}
	bound := false
	for _, role := range config.Team.Roles {
		if role.MemberID != nil && *role.MemberID != "" {
			bound = true
			break
		}
	}
	if !bound {
		return nil
	}
	if a.TT == nil || config.Swarm == "" {
		return okr.ErrInvalid
	}
	ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	out, err := a.TT.RunCtx(ctx, "swarm", "status", config.Swarm, "--json")
	if err != nil {
		return err
	}
	var response struct {
		Data *struct {
			ID             string `json:"id"`
			Archived       bool   `json:"archived"`
			MemberProtocol int    `json:"memberProtocol"`
			Target         struct {
				Kind      string `json:"kind"`
				ProjectID string `json:"projectId"`
			} `json:"target"`
			Members []struct {
				ID       string `json:"id"`
				SwarmID  string `json:"swarm_id"`
				Executor string `json:"executor"`
			} `json:"members"`
		} `json:"data"`
	}
	if err := json.Unmarshal([]byte(out), &response); err != nil {
		return err
	}
	data := response.Data
	if data == nil || data.ID != config.Swarm || data.Archived || data.MemberProtocol != 1 || data.Target.Kind != "project" || data.Target.ProjectID != projectID {
		return okr.ErrInvalid
	}
	for _, role := range config.Team.Roles {
		if role.MemberID == nil || *role.MemberID == "" {
			continue
		}
		matches := 0
		for _, member := range data.Members {
			if member.ID == *role.MemberID && member.SwarmID == data.ID && member.Executor == role.Executor {
				matches++
			}
		}
		if matches != 1 {
			return okr.ErrInvalid
		}
	}
	return nil
}
