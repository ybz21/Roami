package modelgateway

import (
	"net/http"

	"github.com/ybz21/Roami/internal/agentproviders"
)

func catalogProtocol(kind, protocol string) bool {
	return containsField([]string{"anthropic-messages", "openai-responses", "openai-completions"}, protocol) && containsField([]string{"codex", "claude", "opencode", "pi"}, kind)
}

func (h *Handler) sourceModels(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Kind     string `json:"kind"`
		SourceID string `json:"sourceId"`
		Revision string `json:"revision"`
	}
	if decodeBody(w, r, &input) != nil {
		reject(w, 400, "INVALID_MODEL_CATALOG")
		return
	}
	s := h.Catalog
	s.mu.Lock()
	if input.Revision != s.value.Revision {
		s.mu.Unlock()
		reject(w, 409, "MODEL_CATALOG_CHANGED")
		return
	}
	var source *ModelSource
	for _, row := range s.value.Sources {
		if row.ID == input.SourceID {
			copy := row
			source = &copy
		}
	}
	s.mu.Unlock()
	if source == nil || !catalogProtocol(input.Kind, source.Protocol) {
		reject(w, 400, "INVALID_MODEL_PROTOCOL")
		return
	}
	models, err := agentproviders.ReadSourceModels(r.Context(), agentproviders.Profile{BaseURL: source.BaseURL, Protocol: source.Protocol, AuthMode: source.AuthMode, APIKey: source.APIKey})
	s.mu.Lock()
	changed := input.Revision != s.value.Revision
	s.mu.Unlock()
	if changed {
		reject(w, 409, "MODEL_CATALOG_CHANGED")
		return
	}
	if err != nil {
		code := err.Error()
		if !containsField([]string{"MODEL_LIST_UNAUTHORIZED", "MODEL_LIST_UNSUPPORTED", "MODEL_LIST_FAILED"}, code) {
			code = "MODEL_LIST_FAILED"
		}
		reject(w, 502, code)
		return
	}
	valid := []string{}
	for _, model := range models {
		if len(model) <= 200 {
			valid = append(valid, model)
		}
	}
	writeJSON(w, 200, map[string]any{"data": map[string]any{"models": valid}})
}

func nativeProtocol(kind string) string {
	switch kind {
	case "claude":
		return "anthropic-messages"
	case "codex":
		return "openai-responses"
	default:
		return "openai-completions"
	}
}
