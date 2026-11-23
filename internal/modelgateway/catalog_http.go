package modelgateway

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/ybz21/Roami/internal/agentproviders"
	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
)

func (h *Handler) catalogManagement(w http.ResponseWriter, r *http.Request) bool {
	if !strings.HasPrefix(r.URL.Path, "/v1/model-gateway/catalog") {
		return false
	}
	if h.Catalog == nil {
		reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return true
	}
	if r.URL.Path == "/v1/model-gateway/catalog/local-sources" {
		h.localSourcesManagement(w, r)
		return true
	}
	if r.URL.Path == "/v1/model-gateway/catalog/roles" && r.Method == "POST" {
		h.applyRoamiModels(w, r)
		return true
	}
	if r.URL.Path == "/v1/model-gateway/catalog/discover" && r.Method == "POST" {
		h.discoverModels(w, r)
		return true
	}
	if r.URL.Path == "/v1/model-gateway/catalog/source-models" && r.Method == "POST" {
		h.sourceModels(w, r)
		return true
	}
	if r.URL.Path == "/v1/model-gateway/catalog/routing" {
		h.routingView(w, r)
		return true
	}
	s := h.Catalog
	s.mu.Lock()
	defer s.mu.Unlock()
	var err error
	switch {
	case r.URL.Path == "/v1/model-gateway/catalog" && r.Method == "GET":
		writeJSON(w, 200, map[string]any{"data": s.view(r.Context())})
		return true
	case r.URL.Path == "/v1/model-gateway/catalog" && r.Method == "PUT":
		var value ModelCatalog
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&value) != nil || decoder.Decode(new(any)) != io.EOF {
			reject(w, 400, "INVALID_MODEL_CATALOG")
			return true
		}
		if value.Revision == s.value.Revision && !s.applying && !modelcatalog.NewSourcesHaveKeys(value.Sources, s.value.Sources) {
			reject(w, 400, "MODEL_SOURCE_KEY_REQUIRED")
			return true
		}
		err = s.update(r.Context(), value)
		if err == nil {
			writeJSON(w, 200, map[string]any{"data": s.view(r.Context())})
			return true
		}
	case r.URL.Path == "/v1/model-gateway/catalog/apply" && r.Method == "POST":
		var input struct {
			Kind            string `json:"kind"`
			SourceID        string `json:"sourceId"`
			UpstreamModel   string `json:"upstreamModel"`
			Model           string `json:"model"`
			Revision        string `json:"revision"`
			CatalogRevision string `json:"catalogRevision"`
		}
		if decodeBody(w, r, &input) != nil {
			reject(w, 400, "INVALID_MODEL_CATALOG")
			return true
		}
		if input.CatalogRevision != s.value.Revision {
			err = errors.New("MODEL_CATALOG_CHANGED")
			break
		}
		var model *CatalogModel
		if input.Model == gatewayDefaultModel && catalogProtocol(input.Kind, "openai-completions") && input.SourceID == "" && input.UpstreamModel == "" {
			model = s.defaultModel(s.value)
		}
		for _, m := range s.value.Models {
			if m.MatchesGatewayName(input.Model) {
				copy := m
				model = &copy
			}
		}
		created := false
		if input.UpstreamModel != "" {
			upstream := strings.TrimSpace(input.UpstreamModel)
			var source *ModelSource
			for _, row := range s.value.Sources {
				if row.ID == input.SourceID {
					copy := row
					source = &copy
				}
			}
			if input.Model != "" || source == nil || upstream == "" || upstream == source.APIKey || len(upstream) > 200 || strings.ContainsAny(upstream, "\r\n\x00") || !catalogProtocol(input.Kind, source.Protocol) {
				err = catalogError()
				break
			}
			for _, row := range s.value.Models {
				if !row.Aggregate && row.Protocol == source.Protocol && row.Candidates[0].SourceID == source.ID && row.Candidates[0].Model == upstream {
					copy := row
					model = &copy
					break
				}
			}
			if model == nil {
				if len(s.value.Models) >= 1000 {
					err = catalogError()
					break
				}
				id, e := randomCatalogID()
				if e != nil {
					err = e
					break
				}
				model = &CatalogModel{ID: id, Name: upstream, Protocol: source.Protocol, Strategy: "fixed", Candidates: []ModelCandidate{{SourceID: source.ID, Model: upstream}}}
				created = true
			}
		}
		if model == nil || model.HiddenAtGateway(modelcatalog.HiddenGatewayMembers(s.value.Models)) || input.SourceID != "" && !(model.Aggregate && input.SourceID == groupSource || !model.Aggregate && model.Candidates[0].SourceID == input.SourceID) {
			err = catalogError()
			break
		}
		if !catalogProtocol(input.Kind, model.Protocol) {
			err = errors.New("INVALID_MODEL_PROTOCOL")
			break
		}
		view, e := s.agents.View(r.Context(), input.Kind)
		if e != nil {
			err = e
			break
		}
		if view.Revision != input.Revision {
			err = errors.New("AGENT_CONFIG_CHANGED")
			break
		}
		if created {
			next := s.snapshot()
			next.Models = append(next.Models, *model)
			if err = s.persist(next); err != nil {
				break
			}
		}
		if s.value.AgentKeys[input.Kind].Disabled {
			err = errors.New("MODEL_GATEWAY_KEY_DISABLED")
			break
		}
		key := s.credential(input.Kind)
		base := s.baseURL + "/v1"
		protocol := nativeProtocol(input.Kind)
		if protocol == "anthropic-messages" {
			base = s.baseURL
		}
		profileID := ""
		for _, p := range view.Profiles {
			if p.Name == "Roami Gateway" && (p.BaseURL == s.baseURL || strings.HasPrefix(p.BaseURL, s.baseURL+"/")) {
				profileID = p.ID
			}
		}
		authMode := "api_key"
		if input.Kind == "claude" {
			authMode = "bearer"
		}
		selectedModel := model.ID
		if input.Kind == "claude" {
			selectedModel = agentproviders.ClaudeGatewayModelID(selectedModel)
		}
		if input.Model == gatewayDefaultModel {
			selectedModel = gatewayDefaultModel
		}
		var options []agentproviders.ModelOption
		if input.Kind == "pi" || input.Kind == "opencode" {
			options = s.modelOptions(s.value)
		}
		profile, e := s.agents.Save(r.Context(), input.Kind, profileID, agentproviders.ProfileInput{Name: "Roami Gateway", BaseURL: base, Model: selectedModel, ModelName: model.Name, Protocol: protocol, AuthMode: authMode, APIKey: &key, Models: options})
		if e != nil {
			err = e
			break
		}
		// Non-Claude adapters accept API-key credentials, with bearer transport handled by the CLI.
		_, err = s.agents.Apply(r.Context(), input.Kind, profile.ID, input.Revision)
		if err == nil {
			writeJSON(w, 200, map[string]any{"data": s.view(r.Context())})
			return true
		}
	default:
		reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	status := 400
	if err != nil && containsField([]string{"MODEL_CATALOG_CHANGED", "MODEL_CATALOG_IN_USE", "AGENT_CONFIG_CHANGED", "AGENT_CONFIG_INLINE_OVERRIDE", "AGENT_CONFIG_RECOVERY_REQUIRED", "OPENCODE_CONFIG_VERSION_UNKNOWN"}, err.Error()) {
		status = 409
	}
	if err == nil {
		err = catalogError()
	}
	reject(w, status, err.Error())
	return true
}
