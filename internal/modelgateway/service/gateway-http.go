package service

import (
	"context"
	"net/http"
	"strings"

	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
)

func (h *Handler) publicModels(w http.ResponseWriter, r *http.Request) {
	h.servePublicModels(w, r, false)
}

// The TCP listener serves inference and model discovery; management uses the Unix socket.
func (h *Handler) servePublicModels(w http.ResponseWriter, r *http.Request, externalOnly bool) {
	h.mu.Lock()
	if h.closing {
		h.mu.Unlock()
		httpapi.Reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return
	}
	h.wait.Add(1)
	h.mu.Unlock()
	defer h.wait.Done()
	s := h.Catalog
	s.mu.Lock()
	key := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if key == "" {
		key = r.Header.Get("X-Api-Key")
	}
	kind, keyID := s.authenticate(key)
	if externalOnly && (!s.value.LANEnabled || kind != "external") {
		kind = ""
	}
	snapshot := s.snapshot()
	s.mu.Unlock()
	if kind == "" {
		httpapi.Reject(w, 401, "MODEL_GATEWAY_UNAUTHORIZED")
		return
	}
	if r.Method == "GET" && r.URL.Path == "/v1/models" {
		if kind == "codex" && r.URL.Query().Get("client_version") != "" {
			httpapi.WriteJSON(w, 200, codexModelCatalog(s.modelOptions(snapshot)))
			return
		}
		data := []map[string]any{}
		if kind != "claude" && catalogProtocol(kind, "openai-completions") && s.defaultModel(snapshot) != nil {
			data = append(data, map[string]any{"id": gatewayDefaultModel, "type": "model", "object": "model", "display_name": "Roami Default", "owned_by": "roami"})
		}
		hidden := modelcatalog.HiddenGatewayMembers(snapshot.Models)
		names := snapshot.gatewayNames()
		for _, m := range snapshot.Models {
			if (m.Aggregate && !m.IsEnabled()) || m.HiddenAtGateway(hidden) {
				continue
			}
			id := names.publicName(m)
			if kind == "claude" {
				id = claudeModelPrefix + id
			}
			data = append(data, map[string]any{"id": id, "type": "model", "object": "model", "display_name": m.Name, "owned_by": "roami"})
		}
		httpapi.WriteJSON(w, 200, map[string]any{"object": "list", "data": data, "has_more": false})
		return
	}
	protocol := ""
	switch r.URL.Path {
	case "/v1/responses", "/v1/responses/compact":
		protocol = "openai-responses"
	case "/v1/messages":
		protocol = "anthropic-messages"
	case "/v1/chat/completions":
		protocol = "openai-completions"
	}
	if protocol == "" || r.Method != "POST" {
		httpapi.Reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return
	}
	if kind == "codex" && protocol != "openai-responses" || kind == "claude" && protocol != "anthropic-messages" || kind == "roami" && protocol != "openai-completions" {
		httpapi.Reject(w, 400, "INVALID_MODEL_PROTOCOL")
		return
	}
	r = r.WithContext(context.WithValue(r.Context(), gatewayKeyContext{}, keyID))
	h.forwardCatalog(w, r, snapshot, kind, protocol)
}
