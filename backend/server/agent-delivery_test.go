package server

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ybz21/Roami/backend/api"
)

type deliveryTransport struct{ base string }

func (d deliveryTransport) RoundTrip(request *http.Request) (*http.Response, error) {
	copy := request.Clone(request.Context())
	copy.URL.Scheme, copy.URL.Host = "http", strings.TrimPrefix(d.base, "http://")
	return http.DefaultTransport.RoundTrip(copy)
}

func TestAgentDeliveryClaimsPrivatelyAndSettlesExactToken(t *testing.T) {
	sent, settled := 0, false
	notice := api.AgentNotice{ID: "delivery", ClaimToken: "claim-one", EventID: 42, ConversationID: "conversation", BranchID: "branch", MessageID: "message", HidePreview: true, Badge: 3}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Roami-Owner") != "local" || r.Header.Get("Cookie") != "" {
			t.Error("unexpected identity or browser credentials")
		}
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/internal/deliveries/claim":
			_ = json.NewEncoder(w).Encode(map[string]any{"data": notice})
		case "/internal/deliveries/delivery/receipt":
			var body struct {
				ClaimToken string                   `json:"claimToken"`
				Outcome    api.AgentDeliveryOutcome `json:"outcome"`
			}
			if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
				t.Error(err)
			}
			if body.ClaimToken != "claim-one" || body.Outcome.Stage != "adapter_accepted" || body.Outcome.Accepted != 2 {
				t.Errorf("wrong settlement %#v", body)
			}
			settled = true
			_, _ = w.Write([]byte(`{"data":{"state":"delivered"}}`))
		default:
			t.Error("unexpected path " + r.URL.Path)
			w.WriteHeader(404)
		}
	}))
	defer server.Close()
	client := &http.Client{Transport: deliveryTransport{server.URL}}
	err := deliverAgentOnce(context.Background(), client, func(ctx context.Context, got api.AgentNotice) api.AgentDeliveryOutcome {
		if _, ok := ctx.Deadline(); !ok {
			t.Error("delivery has no deadline")
		}
		if got.MessageID != notice.MessageID || got.EventID != 42 {
			t.Error("changed message identity")
		}
		sent++
		return api.AgentDeliveryOutcome{Stage: "adapter_accepted", Accepted: 2}
	})
	if err != nil || sent != 1 || !settled {
		t.Fatalf("delivery failed: %v sent=%d settled=%v", err, sent, settled)
	}
}

func TestAgentDeliveryDoesNotSendMalformedOrUnclaimedNotice(t *testing.T) {
	for _, body := range []string{`{"data":null}`, `{"data":{"id":"x","eventId":1,"claimToken":"c","conversationId":"../escape","branchId":"b","messageId":"m"}}`} {
		t.Run(body, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(body)) }))
			defer server.Close()
			_ = deliverAgentOnce(context.Background(), &http.Client{Transport: deliveryTransport{server.URL}}, func(context.Context, api.AgentNotice) api.AgentDeliveryOutcome {
				t.Fatal("sent an unclaimed or invalid notice")
				return api.AgentDeliveryOutcome{}
			})
		})
	}
}
