package modelgateway

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"net/url"
	"sort"
	"strings"

	"github.com/ybz21/Roami/internal/agentproviders"
)

type localSourceView struct {
	ID          string `json:"id"`
	Revision    string `json:"revision"`
	Kind        string `json:"agentKind"`
	Name        string `json:"name"`
	BaseURL     string `json:"baseUrl"`
	Protocol    string `json:"protocol"`
	Model       string `json:"model"`
	HasKey      bool   `json:"hasKey"`
	Unavailable bool   `json:"unavailable"`
}

func localSourceRevision(source agentproviders.LocalSource) string {
	raw, _ := json.Marshal(source.Profile)
	digest := sha256.Sum256(append([]byte(source.Revision+source.Kind+source.ID), raw...))
	return hex.EncodeToString(digest[:])
}
func (s *CatalogStore) localSources(ctx context.Context) []agentproviders.LocalSource {
	result := []agentproviders.LocalSource{}
	for _, kind := range gatewayAgentKinds {
		if kind == "roami" {
			continue
		}
		rows, err := s.agents.LocalSources(ctx, kind)
		if err != nil {
			continue
		}
		for _, row := range rows {
			if s.isGatewaySource(row.Profile.BaseURL) {
				continue
			}
			source := ModelSource{ID: row.ID, Name: row.Profile.Name, BaseURL: row.Profile.BaseURL, Protocol: row.Profile.Protocol, AuthMode: row.Profile.AuthMode, APIKey: row.Profile.APIKey}
			if _, err := s.validatedSource(source, ModelSource{}); err != nil {
				row.Unavailable = true
				row.Profile.APIKey = ""
			}
			result = append(result, row)
		}
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].Kind != result[j].Kind {
			return result[i].Kind < result[j].Kind
		}
		return result[i].ID < result[j].ID
	})
	return result
}
func (h *Handler) localSourcesManagement(w http.ResponseWriter, r *http.Request) {
	s := h.Catalog
	s.mu.Lock()
	defer s.mu.Unlock()
	if r.Method == "GET" {
		result := []localSourceView{}
		for _, row := range s.localSources(r.Context()) {
			p := row.Profile
			result = append(result, localSourceView{ID: row.ID, Revision: localSourceRevision(row), Kind: row.Kind, Name: p.Name, BaseURL: redactedSourceEndpoint(p.BaseURL), Protocol: p.Protocol, Model: p.Model, HasKey: p.APIKey != "", Unavailable: row.Unavailable})
		}
		writeJSON(w, 200, map[string]any{"data": map[string]any{"sources": result, "revision": s.value.Revision}})
		return
	}
	if r.Method != "POST" {
		reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return
	}
	var input struct {
		ID              string `json:"id"`
		Revision        string `json:"revision"`
		CatalogRevision string `json:"catalogRevision"`
	}
	if decodeBody(w, r, &input) != nil {
		reject(w, 400, "INVALID_MODEL_CATALOG")
		return
	}
	if input.CatalogRevision != s.value.Revision {
		reject(w, 409, "MODEL_CATALOG_CHANGED")
		return
	}
	for _, row := range s.localSources(r.Context()) {
		if row.ID != input.ID {
			continue
		}
		if input.Revision != localSourceRevision(row) {
			reject(w, 409, "AGENT_CONFIG_CHANGED")
			return
		}
		if row.Unavailable {
			reject(w, 400, "MODEL_LOCAL_SOURCE_UNSUPPORTED")
			return
		}
		p := row.Profile
		next := s.snapshot()
		sourceID := "local-" + row.ID
		for _, source := range next.Sources {
			if source.BaseURL == p.BaseURL && source.Protocol == p.Protocol && source.APIKey == p.APIKey {
				sourceID = source.ID
				break
			}
		}
		found := false
		for _, source := range next.Sources {
			if source.ID == sourceID {
				found = true
			}
		}
		if found {
			reject(w, 409, "MODEL_LOCAL_SOURCE_EXISTS")
			return
		}
		next.Sources = append(next.Sources, ModelSource{ID: sourceID, Name: p.Name, BaseURL: p.BaseURL, Protocol: p.Protocol, AuthMode: p.AuthMode, APIKey: p.APIKey})
		if p.Model != "" && len(p.Model) <= 200 {
			next.Models = append(next.Models, CatalogModel{ID: sourceID + "-model", Name: p.Model, Protocol: p.Protocol, Strategy: "fixed", Candidates: []ModelCandidate{{sourceID, p.Model}}})
		}
		if err := s.update(r.Context(), next); err != nil {
			code := err.Error()
			status := 400
			if errors.Is(err, context.Canceled) {
				status = 503
			}
			reject(w, status, code)
			return
		}
		writeJSON(w, 200, map[string]any{"data": s.view(r.Context())})
		return
	}
	reject(w, 409, "AGENT_CONFIG_CHANGED")
}

func redactedSourceEndpoint(raw string) string {
	u, err := url.Parse(raw)
	if err != nil {
		return ""
	}
	u.User, u.RawQuery, u.Fragment = nil, "", ""
	return u.String()
}
func (s *CatalogStore) isGatewaySource(raw string) bool {
	if s.baseURL == "" {
		return false
	}
	u, err := url.Parse(strings.TrimRight(raw, "/"))
	if err != nil {
		return false
	}
	gateway, err := url.Parse(s.baseURL)
	if err != nil {
		return false
	}
	return u.Port() == gateway.Port() && containsField([]string{gateway.Hostname(), "localhost", "127.0.0.1", "::1"}, u.Hostname())
}
