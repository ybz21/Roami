package modelgateway

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"sort"
	"sync"
	"time"

	"github.com/ybz21/Roami/internal/agentproviders"
	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
)

type CapabilityFact struct {
	Support  string `json:"support"`
	Evidence string `json:"evidence"`
	Delivery string `json:"delivery"`
}
type ModelDirectoryRow struct {
	ID               string                    `json:"id"`
	Name             string                    `json:"name"`
	GatewayAlias     string                    `json:"gatewayAlias,omitempty"`
	GatewayHidden    bool                      `json:"gatewayHidden,omitempty"`
	Kind             string                    `json:"kind"`
	Protocol         string                    `json:"protocol"`
	Configured       bool                      `json:"configured"`
	Enabled          bool                      `json:"enabled"`
	FreeOnly         bool                      `json:"freeOnly"`
	ContextWindow    int                       `json:"contextWindow,omitempty"`
	MaxOutputTokens  int                       `json:"maxOutputTokens,omitempty"`
	InputModalities  []string                  `json:"inputModalities,omitempty"`
	OutputModalities []string                  `json:"outputModalities,omitempty"`
	InputPrice       *float64                  `json:"inputPrice,omitempty"`
	OutputPrice      *float64                  `json:"outputPrice,omitempty"`
	Pricing          string                    `json:"pricing"`
	Capabilities     map[string]CapabilityFact `json:"capabilities"`
	Candidates       []ModelCandidate          `json:"candidates"`
}
type sourceDirectoryEntry struct {
	Fingerprint string
	Details     []agentproviders.SourceModelDetail
	ObservedAt  time.Time
	Problem     string
}

func sourceDirectoryFingerprint(source ModelSource) string {
	raw, _ := json.Marshal(struct {
		ID, Connector, PluginSourceID, PluginRevision, BaseURL, Protocol, AuthMode, Credential string
		SkipTLSVerification                                                                    bool              `json:",omitempty"`
		Headers                                                                                map[string]string `json:",omitempty"`
	}{source.ID, source.Connector, source.PluginSourceID, source.PluginRevision, source.BaseURL, source.Protocol, source.AuthMode, source.APIKey, source.SkipTLSVerification, source.Headers})
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:])
}
func (s *CatalogStore) rememberSourceDetails(source ModelSource, revision string, details []agentproviders.SourceModelDetail) {
	s.rememberSourceDirectory(source, revision, sourceDirectoryEntry{Fingerprint: sourceDirectoryFingerprint(source), Details: details, ObservedAt: time.Now()})
}
func (s *CatalogStore) rememberSourceDirectory(source ModelSource, revision string, entry sourceDirectoryEntry) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if revision != s.value.Revision {
		return
	}
	// Unsaved discovery must never replace a configured source's evidence.
	for _, saved := range s.value.Sources {
		if saved.ID == source.ID && sourceDirectoryFingerprint(saved) == entry.Fingerprint {
			if s.directory == nil {
				s.directory = map[string]sourceDirectoryEntry{}
			}
			s.directory[source.ID] = entry
		}
	}
}

func (h *Handler) routingSourceDirectory(ctx context.Context, source ModelSource, revision string) sourceDirectoryEntry {
	s := h.Catalog
	fingerprint := sourceDirectoryFingerprint(source)
	cached := func() (sourceDirectoryEntry, bool) {
		s.mu.Lock()
		entry := s.directory[source.ID]
		s.mu.Unlock()
		ttl := 15 * time.Minute
		if entry.Problem != "" {
			ttl = time.Minute
		}
		return entry, entry.Fingerprint == fingerprint && time.Since(entry.ObservedAt) < ttl
	}
	if entry, ok := cached(); ok {
		return entry
	}
	result := s.directoryReads.DoChan(revision+"/"+fingerprint, func() (any, error) {
		if entry, ok := cached(); ok {
			return entry, nil
		}
		callCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 6*time.Second)
		defer cancel()
		_, details, err := h.fetchSourceModels(callCtx, source)
		entry := sourceDirectoryEntry{Fingerprint: fingerprint, Details: details, ObservedAt: time.Now()}
		if err != nil {
			entry.Details, entry.Problem = nil, "directory"
			if err.Error() == "MODEL_LIST_UNAUTHORIZED" {
				entry.Problem = "authorization"
			}
		}
		s.rememberSourceDirectory(source, revision, entry)
		return entry, nil
	})
	select {
	case <-ctx.Done():
		return sourceDirectoryEntry{Problem: "directory"}
	case result := <-result:
		return result.Val.(sourceDirectoryEntry)
	}
}
func unknownCapabilities() map[string]CapabilityFact {
	facts := map[string]CapabilityFact{}
	for _, name := range []string{"text", "image", "audio", "video", "tools", "reasoning", "structuredOutput", "streaming"} {
		facts[name] = CapabilityFact{"unknown", "unknown", "unknown"}
	}
	return facts
}
func advertisedCapabilities(detail agentproviders.SourceModelDetail) map[string]CapabilityFact {
	facts := unknownCapabilities()
	set := func(name string, value bool) {
		support := "unsupported"
		if value {
			support = "supported"
		}
		facts[name] = CapabilityFact{support, "advertised", "unknown"}
	}
	if len(detail.InputModalities) > 0 {
		for _, name := range []string{"text", "image", "audio", "video"} {
			set(name, containsField(detail.InputModalities, name))
		}
	}
	for name, value := range map[string]*bool{"tools": detail.Tools, "reasoning": detail.Reasoning, "structuredOutput": detail.StructuredOutput} {
		if value != nil {
			set(name, *value)
		}
	}
	return facts
}
func (s *CatalogStore) directoryRows(ctx context.Context, catalog ModelCatalog, all bool) []ModelDirectoryRow {
	pricing, _ := s.ledger.Configuration()
	details := map[ModelCandidate]agentproviders.SourceModelDetail{}
	pluginFree := map[ModelCandidate]bool{}
	for _, source := range catalog.Sources {
		s.mu.Lock()
		entry := s.directory[source.ID]
		s.mu.Unlock()
		if entry.Fingerprint == sourceDirectoryFingerprint(source) && time.Since(entry.ObservedAt) < 15*time.Minute {
			for _, detail := range entry.Details {
				details[ModelCandidate{source.ID, detail.ID}] = detail
			}
		}
		if source.PluginSourceID != "" && s.plugins != nil {
			if saved, err := s.plugins.ReadSource(source.PluginSourceID); err == nil {
				if provider, err := s.plugins.CachedProvider(saved); err == nil && !provider.FellBack {
					for _, model := range provider.Models {
						candidate := ModelCandidate{source.ID, model.ID}
						if provider.SignedIn && accountPricingModel(&model, len(provider.Accounts)).Free {
							pluginFree[candidate] = true
						}
						if _, exists := details[candidate]; exists {
							continue
						}
						tools, reasoning := model.Tools, model.Reasoning
						detail := agentproviders.SourceModelDetail{ID: model.ID, Name: model.Name, Context: model.Context, Output: model.Output, Tools: &tools, Reasoning: &reasoning, InputModalities: []string{"text"}}
						if model.Image {
							detail.InputModalities = append(detail.InputModalities, "image")
						}
						if model.Free {
							zero := 0.0
							detail.InputPrice = &zero
							detail.OutputPrice = &zero
						}
						details[candidate] = detail
					}
				}
			}
		}
	}
	confirmedFree := func(candidate ModelCandidate) bool {
		if rule, exists := pricing.Pricing.sourceRule(candidate.SourceID, candidate.Model); exists {
			return rule.Mode == "free" && rule.Confirmed
		}
		return pluginFree[candidate]
	}
	freeRoutePrice := func(id string) bool {
		price, overridden := pricing.Pricing.lookup(id)
		return !overridden || price == (ModelPricing{})
	}
	byID := map[string]CatalogModel{}
	for _, model := range catalog.Models {
		byID[model.ID] = model
	}
	var allMembersFree func(CatalogModel, int) bool
	freePools := map[string]bool{}
	allMembersFree = func(model CatalogModel, depth int) bool {
		if depth > 8 || len(model.Candidates) == 0 {
			return false
		}
		if result, seen := freePools[model.ID]; seen {
			return result
		}
		freePools[model.ID] = false
		for _, candidate := range model.Candidates {
			if candidate.SourceID == groupSource {
				if !allMembersFree(byID[candidate.Model], depth+1) {
					return false
				}
			} else if !confirmedFree(candidate) {
				return false
			}
		}
		freePools[model.ID] = true
		return true
	}
	configured := map[ModelCandidate]bool{}
	rows := []ModelDirectoryRow{}
	hidden := modelcatalog.HiddenGatewayMembers(catalog.Models)
	for _, model := range catalog.Models {
		kind := "single"
		if model.Aggregate {
			kind = "aggregate"
		}
		entry := ModelDirectoryRow{ID: model.ID, Name: model.Name, Kind: kind, Protocol: model.Protocol, Configured: true, Enabled: model.IsEnabled(), FreeOnly: model.FreeOnly, Pricing: "unknown", Capabilities: unknownCapabilities(), Candidates: model.Candidates}
		entry.GatewayAlias, entry.GatewayHidden = model.GatewayAlias, model.HiddenAtGateway(hidden)
		if model.FreeOnly {
			entry.Pricing = "free-only"
		} else if model.Aggregate && freeRoutePrice(model.ID) && allMembersFree(model, 0) {
			entry.Pricing = "confirmed-free"
		}
		if !model.Aggregate && len(model.Candidates) == 1 {
			candidate := model.Candidates[0]
			configured[candidate] = true
			if detail, ok := details[candidate]; ok {
				entry.Capabilities = advertisedCapabilities(detail)
				entry.ContextWindow, entry.MaxOutputTokens = detail.Context, detail.Output
				entry.InputModalities, entry.OutputModalities = detail.InputModalities, detail.OutputModalities
				entry.InputPrice, entry.OutputPrice = detail.InputPrice, detail.OutputPrice
				if detail.InputPrice != nil && detail.OutputPrice != nil && *detail.InputPrice == 0 && *detail.OutputPrice == 0 {
					entry.Pricing = "advertised-zero"
				} else if detail.InputPrice != nil && *detail.InputPrice > 0 || detail.OutputPrice != nil && *detail.OutputPrice > 0 {
					entry.Pricing = "metered"
				}
			}
			if confirmedFree(candidate) && freeRoutePrice(model.ID) {
				entry.Pricing = "confirmed-free"
			} else if rule, exists := pricing.Pricing.sourceRule(candidate.SourceID, candidate.Model); exists && rule.Mode == "tokens" {
				entry.Pricing = "metered"
			}
		}
		// An aggregate's union is not a promise that the next selected member supports it.
		rows = append(rows, entry)
	}
	if all {
		for candidate, detail := range details {
			if configured[candidate] {
				continue
			}
			entry := ModelDirectoryRow{ID: candidate.Model, Name: detail.Name, Kind: "single", Pricing: "unknown", Capabilities: advertisedCapabilities(detail), Candidates: []ModelCandidate{candidate}, ContextWindow: detail.Context, MaxOutputTokens: detail.Output, InputModalities: detail.InputModalities, OutputModalities: detail.OutputModalities, InputPrice: detail.InputPrice, OutputPrice: detail.OutputPrice}
			entry.GatewayHidden = hidden[candidate]
			for _, source := range catalog.Sources {
				if source.ID == candidate.SourceID {
					entry.Protocol = source.Protocol
				}
			}
			if detail.InputPrice != nil && detail.OutputPrice != nil && *detail.InputPrice == 0 && *detail.OutputPrice == 0 {
				entry.Pricing = "advertised-zero"
			} else if detail.InputPrice != nil && *detail.InputPrice > 0 || detail.OutputPrice != nil && *detail.OutputPrice > 0 {
				entry.Pricing = "metered"
			}
			rows = append(rows, entry)
		}
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Configured != rows[j].Configured {
			return rows[i].Configured
		}
		if rows[i].Kind != rows[j].Kind {
			return rows[i].Kind == "aggregate"
		}
		return rows[i].ID < rows[j].ID
	})
	return rows
}
func (h *Handler) modelDirectoryManagement(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path != "/v1/model-gateway/models" {
		return false
	}
	if r.Method != "GET" {
		reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	if h.Catalog == nil {
		reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return true
	}
	s := h.Catalog
	s.mu.Lock()
	catalog := s.snapshot()
	s.mu.Unlock()
	failures := []string{}
	if r.URL.Query().Get("refresh") == "true" {
		ctx, cancel := context.WithTimeout(r.Context(), 12*time.Second)
		defer cancel()
		var wait sync.WaitGroup
		var mu sync.Mutex
		gate := make(chan struct{}, 4)
		for _, source := range catalog.Sources {
			wait.Add(1)
			go func(source ModelSource) {
				defer wait.Done()
				select {
				case gate <- struct{}{}:
					defer func() { <-gate }()
				case <-ctx.Done():
					mu.Lock()
					failures = append(failures, source.ID)
					mu.Unlock()
					return
				}
				_, details, err := h.fetchSourceModels(ctx, source)
				if err != nil {
					mu.Lock()
					failures = append(failures, source.ID)
					mu.Unlock()
				} else {
					s.rememberSourceDetails(source, catalog.Revision, details)
				}
			}(source)
		}
		wait.Wait()
		sort.Strings(failures)
	}
	rows := s.directoryRows(r.Context(), catalog, r.URL.Query().Get("all") == "true")
	filtered := []ModelDirectoryRow{}
	includeHidden := r.URL.Query().Get("includeHidden") == "true"
	for _, row := range rows {
		if row.GatewayHidden && !includeHidden {
			continue
		}
		if r.URL.Query().Get("free") == "true" && !row.FreeOnly && row.Pricing != "confirmed-free" {
			continue
		}
		if capability := r.URL.Query().Get("capability"); capability != "" && row.Capabilities[capability].Support != "supported" {
			continue
		}
		filtered = append(filtered, row)
	}
	s.mu.Lock()
	changed := s.value.Revision != catalog.Revision
	s.mu.Unlock()
	if changed {
		reject(w, 409, "MODEL_CATALOG_CHANGED")
		return true
	}
	writeJSON(w, 200, map[string]any{"data": map[string]any{"revision": catalog.Revision, "models": filtered, "refreshFailures": failures}})
	return true
}
