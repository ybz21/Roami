package api

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	webpush "github.com/SherClockHolmes/webpush-go"
)

type AgentNotice struct {
	ID             string `json:"id"`
	ClaimToken     string `json:"claimToken"`
	EventID        int64  `json:"eventId"`
	ConversationID string `json:"conversationId"`
	BranchID       string `json:"branchId"`
	MessageID      string `json:"messageId"`
	HidePreview    bool   `json:"hidePreview"`
	Title          string `json:"title"`
	Body           string `json:"body"`
	Badge          int    `json:"badge"`
}

type AgentDeliveryOutcome struct {
	Stage     string `json:"stage"`
	Accepted  int    `json:"accepted"`
	Failed    int    `json:"failed"`
	Unknown   int    `json:"unknown"`
	NoDevices int    `json:"noDevices"`
}

// Accepted means enqueued to an App connection or accepted by a push gateway, never device display.
func (a *API) DeliverAgentNotice(ctx context.Context, notice AgentNotice) AgentDeliveryOutcome {
	p := PushPayload{ID: notice.EventID, Type: "agent.message", Conversation: notice.ConversationID,
		Branch: notice.BranchID, Message: notice.MessageID, Title: notice.Title, Body: notice.Body,
		HidePreview: notice.HidePreview, Badge: notice.Badge}
	if p.Title == "" || p.Title == "New conversation" {
		p.Title = "Roami"
	}
	if notice.HidePreview {
		p.Title, p.Body = "Roami", ""
	}
	if a.Prefs != nil {
		if locale, ok := a.Prefs.get()["locale"].(string); ok && (locale == "zh-CN" || locale == "en-US") {
			p.Locale = locale
		}
	}
	accepted, failed := a.Events.enqueue(p)
	result := AgentDeliveryOutcome{Accepted: accepted, Failed: failed}
	if a.Push != nil {
		push := a.Push.deliverAgent(ctx, p, &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }})
		result.Accepted += push.Accepted
		result.Failed += push.Failed
		result.Unknown += push.Unknown
	}
	switch {
	case result.Unknown > 0 || (result.Accepted > 0 && result.Failed > 0):
		result.Stage = "unknown"
	case result.Accepted > 0:
		result.Stage = "adapter_accepted"
	case result.Failed > 0:
		result.Stage = "failed"
	default:
		result.Stage, result.NoDevices = "no_devices", 1
	}
	return result
}

func (s *PushStore) deliverAgent(ctx context.Context, p PushPayload, client webpush.HTTPClient) AgentDeliveryOutcome {
	if s.priv == "" {
		return AgentDeliveryOutcome{}
	}
	body, _ := json.Marshal(p)
	s.mu.Lock()
	targets := make([]pushDevice, 0, len(s.devices))
	for _, d := range s.devices {
		targets = append(targets, d)
	}
	s.mu.Unlock()
	var mu sync.Mutex
	var result AgentDeliveryOutcome
	jobs := make(chan pushDevice)
	var workers sync.WaitGroup
	for i := 0; i < 4; i++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for device := range jobs {
				accepted, failed, unknown := 0, 0, 0
				if ctx.Err() != nil {
					failed = 1
				} else {
					response, err := webpush.SendNotificationWithContext(ctx, body, &device.Sub, &webpush.Options{
						HTTPClient: client, Subscriber: "mailto:roami@localhost", VAPIDPublicKey: s.pub,
						VAPIDPrivateKey: s.priv, TTL: 600, Urgency: webpush.UrgencyNormal,
					})
					if err != nil {
						unknown = 1
					} else {
						_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 4096))
						_ = response.Body.Close()
						if response.StatusCode >= 200 && response.StatusCode < 300 {
							accepted = 1
						} else {
							failed = 1
						}
						if response.StatusCode == http.StatusGone || response.StatusCode == http.StatusNotFound {
							s.mu.Lock()
							if current, ok := s.devices[device.Device]; ok && current.Sub.Endpoint == device.Sub.Endpoint && current.At == device.At && current.Sub.Keys == device.Sub.Keys {
								delete(s.devices, device.Device)
								s.save()
							}
							s.mu.Unlock()
						}
					}
				}
				mu.Lock()
				result.Accepted += accepted
				result.Failed += failed
				result.Unknown += unknown
				mu.Unlock()
			}
		}()
	}
	for _, device := range targets {
		jobs <- device
	}
	close(jobs)
	workers.Wait()
	return result
}

func ValidAgentNotice(n AgentNotice) bool {
	if n.ID == "" || len(n.ID) > 200 || n.ClaimToken == "" || len(n.ClaimToken) > 200 || n.EventID < 1 || n.Badge < 0 || len(n.Title) > 1000 || len(n.Body) > 2000 {
		return false
	}
	for _, id := range []string{n.ConversationID, n.BranchID, n.MessageID} {
		if id == "" || len(id) > 200 || strings.ContainsAny(id, "/?#\\") {
			return false
		}
	}
	return true
}
