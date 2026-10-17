package api

import (
	"context"
	"crypto/ecdh"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	webpush "github.com/SherClockHolmes/webpush-go"
	"io"
	"net/http"
	"strings"
	"testing"
)

func TestAgentNoticeEnqueuesCanonicalUnreadAndHidesPreview(t *testing.T) {
	a := &API{}
	ch := a.Events.subscribe()
	defer a.Events.unsubscribe(ch)
	outcome := a.DeliverAgentNotice(context.Background(), AgentNotice{EventID: 42, ConversationID: "conversation", BranchID: "branch", MessageID: "message", Title: "Private title", Body: "Private body", HidePreview: true, Badge: 7})
	if outcome.Stage != "adapter_accepted" || outcome.Accepted != 1 {
		t.Fatalf("not enqueued: %#v", outcome)
	}
	payload := <-ch
	if payload.Type != "agent.message" || payload.ID != 42 || payload.Conversation != "conversation" || payload.Branch != "branch" || payload.Message != "message" || payload.Badge != 7 {
		t.Fatalf("lost canonical identity: %#v", payload)
	}
	if payload.Title != "Roami" || payload.Body != "" || !payload.HidePreview || payload.Session != "" || len(payload.Actions) != 0 {
		t.Fatalf("preview leaked or session actions attached: %#v", payload)
	}
}

func TestAgentNoticeNoDevicesAndFullAppQueueAreNotDeliverySuccess(t *testing.T) {
	a := &API{}
	if outcome := a.DeliverAgentNotice(context.Background(), AgentNotice{}); outcome.Stage != "no_devices" || outcome.NoDevices != 1 {
		t.Fatalf("no recipient claimed success: %#v", outcome)
	}
	ch := a.Events.subscribe()
	defer a.Events.unsubscribe(ch)
	for i := 0; i < cap(ch); i++ {
		ch <- PushPayload{ID: int64(i)}
	}
	if outcome := a.DeliverAgentNotice(context.Background(), AgentNotice{}); outcome.Stage != "failed" || outcome.Failed != 1 || outcome.Accepted != 0 {
		t.Fatalf("full queue claimed success: %#v", outcome)
	}
}

type agentPushHTTP struct {
	status int
	fail   bool
}

func (h agentPushHTTP) Do(r *http.Request) (*http.Response, error) {
	if r.Context().Err() != nil {
		return nil, r.Context().Err()
	}
	if h.fail {
		return nil, fmt.Errorf("injected transport failure")
	}
	return &http.Response{StatusCode: h.status, Body: io.NopCloser(strings.NewReader("")), Header: make(http.Header)}, nil
}

func TestAgentPushGatewayAcceptanceFailureAndUnknownAreDistinct(t *testing.T) {
	privateKey, publicKey, err := webpush.GenerateVAPIDKeys()
	if err != nil {
		t.Fatal(err)
	}
	deviceKey, err := ecdh.P256().GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	for _, scenario := range []struct {
		name                      string
		client                    agentPushHTTP
		accepted, failed, unknown int
		removed                   bool
	}{
		{"accepted", agentPushHTTP{status: 201}, 1, 0, 0, false},
		{"rejected", agentPushHTTP{status: 503}, 0, 1, 0, false},
		{"expired", agentPushHTTP{status: 410}, 0, 1, 0, true},
		{"unknown", agentPushHTTP{fail: true}, 0, 0, 1, false},
	} {
		t.Run(scenario.name, func(t *testing.T) {
			store := &PushStore{dir: t.TempDir(), pub: publicKey, priv: privateKey, devices: map[string]pushDevice{"device": {Device: "device", Sub: webpush.Subscription{Endpoint: "https://gateway.test/push", Keys: webpush.Keys{P256dh: base64.RawURLEncoding.EncodeToString(deviceKey.PublicKey().Bytes()), Auth: base64.RawURLEncoding.EncodeToString(make([]byte, 16))}}}}}
			result := store.deliverAgent(context.Background(), PushPayload{Type: "agent.message", ID: 42}, scenario.client)
			if result.Accepted != scenario.accepted || result.Failed != scenario.failed || result.Unknown != scenario.unknown {
				t.Fatalf("incorrect gateway evidence: %#v", result)
			}
			if (store.Count() == 0) != scenario.removed {
				t.Fatalf("subscription removal mismatch: %d", store.Count())
			}
		})
	}
}
