package service

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
	"github.com/ybz21/Roami/internal/modelgateway/directory"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	"github.com/ybz21/Roami/internal/modelgateway/routing"
)

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
func (s *CatalogStore) directoryRows(catalog ModelCatalog, all bool) []directory.Row {
	pricing, _ := s.state.accounting.Configuration()
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
						if provider.SignedIn && routing.AccountPricingModel(&model, len(provider.Accounts)).Free {
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
	return directory.Build(catalog.Models, catalog.Sources, details, pluginFree, pricing.Pricing, all)
}
func (h *Handler) modelDirectoryManagement(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path != "/v1/model-gateway/models" {
		return false
	}
	if r.Method != "GET" {
		httpapi.Reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	if h.Catalog == nil {
		httpapi.Reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
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
	rows := s.directoryRows(catalog, r.URL.Query().Get("all") == "true")
	filtered := []directory.Row{}
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
		httpapi.Reject(w, 409, "MODEL_CATALOG_CHANGED")
		return true
	}
	httpapi.WriteJSON(w, 200, map[string]any{"data": map[string]any{"revision": catalog.Revision, "models": filtered, "refreshFailures": failures}})
	return true
}
