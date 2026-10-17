package server

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"time"

	"github.com/ybz21/Roami/backend/api"
	"github.com/ybz21/Roami/backend/config"
	"github.com/ybz21/Roami/internal/agentruntime"
)

func agentDeliveryLoop(ctx context.Context, cfg Config, handler *api.API) {
	paths, err := agentruntime.Resolve(config.Home(), cfg.DataDir)
	if err != nil {
		return
	}
	client := &http.Client{Transport: agentruntime.Transport(paths.Socket), Timeout: 15 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	defer client.CloseIdleConnections()
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			_ = deliverAgentOnce(ctx, client, handler.DeliverAgentNotice)
		}
	}
}

func deliverAgentOnce(ctx context.Context, client *http.Client, send func(context.Context, api.AgentNotice) api.AgentDeliveryOutcome) error {
	var reply struct {
		Data *api.AgentNotice `json:"data"`
	}
	if err := agentDeliveryRequest(ctx, client, "/internal/deliveries/claim", nil, &reply); err != nil {
		return err
	}
	if reply.Data == nil {
		return nil
	}
	notice := *reply.Data
	if !api.ValidAgentNotice(notice) {
		return fmt.Errorf("INVALID_AGENT_DELIVERY")
	}
	deadline, cancel := context.WithTimeout(ctx, 10*time.Second)
	outcome := send(deadline, notice)
	cancel()
	body := map[string]any{"claimToken": notice.ClaimToken, "outcome": outcome}
	return agentDeliveryRequest(ctx, client, "/internal/deliveries/"+url.PathEscape(notice.ID)+"/receipt", body, nil)
}

func agentDeliveryRequest(ctx context.Context, client *http.Client, path string, body any, output any) error {
	var input io.Reader
	if body != nil {
		content, err := json.Marshal(body)
		if err != nil {
			return err
		}
		input = bytes.NewReader(content)
	}
	request, err := http.NewRequestWithContext(ctx, "POST", "http://roami-agent"+path, input)
	if err != nil {
		return err
	}
	request.Header.Set("X-Roami-Owner", "local")
	request.Header.Set("Content-Type", "application/json")
	response, err := client.Do(request)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("AGENT_DELIVERY_UNAVAILABLE")
	}
	if output != nil {
		return json.NewDecoder(io.LimitReader(response.Body, 64<<10)).Decode(output)
	}
	_, err = io.Copy(io.Discard, io.LimitReader(response.Body, 64<<10))
	return err
}
