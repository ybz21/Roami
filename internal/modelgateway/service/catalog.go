package service

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"slices"
	"strings"
	"sync"

	"github.com/ybz21/Roami/internal/agent"
	"github.com/ybz21/Roami/internal/agentproviders"
	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/hostroute"
	"github.com/ybz21/Roami/internal/modelgateway/routing"
	"github.com/ybz21/Roami/internal/modelplugins"
	"golang.org/x/sync/singleflight"
)

const groupSource = modelcatalog.GroupSource

type ModelSource = modelcatalog.ModelSource
type ModelCandidate = modelcatalog.ModelCandidate
type CatalogModel = modelcatalog.CatalogModel

type ModelCatalog struct {
	Revision          string                   `json:"revision"`
	Sources           []ModelSource            `json:"sources"`
	Models            []CatalogModel           `json:"models"`
	Drafts            []CatalogModel           `json:"drafts"`
	BaseURL           string                   `json:"baseUrl,omitempty"`
	Uses              map[string][]string      `json:"uses"`
	Port              int                      `json:"-"`
	LANEnabled        bool                     `json:"-"`
	Token             string                   `json:"-"`
	AccessKey         gatewayAccessKey         `json:"-"`
	AccessKeys        []gatewayAccessKey       `json:"-"`
	RolesBackup       map[string]any           `json:"-"`
	AgentKeys         map[string]agentKeyState `json:"-"`
	CanRestoreRoami   bool                     `json:"canRestoreRoami"`
	RoamiModels       map[string]string        `json:"roamiModels"`
	DefaultModel      string                   `json:"defaultModel,omitempty"`
	QualifiedModelIDs map[string]string        `json:"qualifiedModelIds,omitempty"`
}
type catalogDisk struct {
	Catalog     ModelCatalog             `json:"catalog"`
	Port        int                      `json:"port"`
	LANEnabled  bool                     `json:"lanEnabled,omitempty"`
	Token       string                   `json:"token"`
	AccessKey   gatewayAccessKey         `json:"accessKey,omitempty"`
	AccessKeys  []gatewayAccessKey       `json:"accessKeys,omitempty"`
	RolesBackup map[string]any           `json:"rolesBackup,omitempty"`
	AgentKeys   map[string]agentKeyState `json:"agentKeys,omitempty"`
}
type CatalogStore struct {
	directory      map[string]sourceDirectoryEntry
	directoryReads singleflight.Group
	mu             sync.Mutex
	state          *gatewayState
	value          ModelCatalog
	baseURL        string
	agents         *agentproviders.Store
	applying       bool
	agentSocket    string
	plugins        *modelplugins.Manager
}

func catalogError() error { return modelcatalog.ErrInvalid }
func randomCatalogID() (string, error) {
	var b [24]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}
func (s *CatalogStore) uses(ctx context.Context) map[string][]string {
	uses, _ := s.modelReferences(ctx, true)
	names := s.value.gatewayNames()
	for _, model := range s.value.Models {
		for _, alias := range names.additionalNames(model) {
			for _, use := range uses[alias] {
				if !slices.Contains(uses[model.ID], use) {
					uses[model.ID] = append(uses[model.ID], use)
				}
			}
			delete(uses, alias)
		}
	}
	return uses
}
func (s *CatalogStore) references(ctx context.Context) (map[string][]string, bool) {
	return s.modelReferences(ctx, false)
}
func (s *CatalogStore) modelReferences(ctx context.Context, activeOnly bool) (map[string][]string, bool) {
	uses := map[string][]string{}
	known := true
	for _, role := range []string{"main", "worker"} {
		if route, err := hostroute.Read(s.state.paths, role); err == nil && route.Endpoint == s.baseURL+"/v1" {
			uses[route.Model] = append(uses[route.Model], "roami")
		}
	}
	for _, kind := range agent.Kinds() {
		if !agent.Describe(agent.Get(kind)).Models {
			continue
		}
		view, err := s.agents.View(ctx, kind)
		if err != nil {
			known = false
			continue
		}
		add := func(model string) {
			model = s.value.catalogModelID(kind, model)
			if model == gatewayDefaultModel {
				if resolved := s.defaultModel(s.value); resolved != nil {
					model = resolved.ID
				}
			}
			for _, consumer := range uses[model] {
				if consumer == kind {
					return
				}
			}
			uses[model] = append(uses[model], kind)
		}
		if view.Current.Model != "" && (view.Current.BaseURL == s.baseURL || strings.HasPrefix(view.Current.BaseURL, s.baseURL+"/")) {
			add(view.Current.Model)
		}
		if !activeOnly {
			for _, p := range view.Profiles {
				if p.BaseURL == s.baseURL || strings.HasPrefix(p.BaseURL, s.baseURL+"/") {
					add(p.Model)
				}
			}
		}
	}
	return uses, known
}
func (s *CatalogStore) view(ctx context.Context) ModelCatalog {
	v := s.snapshot()
	v.BaseURL = s.baseURL
	v.Uses = s.uses(ctx)
	hidden := modelcatalog.HiddenGatewayMembers(v.Models)
	names := v.gatewayNames()
	v.QualifiedModelIDs = names.qualified
	for i, model := range v.Models {
		v.Models[i].GatewayHidden = model.HiddenAtGateway(hidden)
	}
	v.CanRestoreRoami = s.value.RolesBackup != nil
	v.RoamiModels = map[string]string{}
	if model := s.defaultModel(s.value); model != nil {
		v.DefaultModel = model.ID
	}
	for _, role := range []string{"main", "worker"} {
		if route, err := hostroute.Read(s.state.paths, role); err == nil {
			v.RoamiModels[role] = route.Model
			if strings.TrimRight(route.Endpoint, "/") == s.baseURL+"/v1" {
				if model := v.findGatewayModel(route.Model); model != nil {
					v.RoamiModels[role] = model.ID
				}
			}
		}
	}
	for i := range v.Sources {
		v.Sources[i] = v.Sources[i].Public()
		if v.Sources[i].PluginSourceID != "" && s.plugins != nil {
			if source, err := s.plugins.ReadSource(v.Sources[i].PluginSourceID); err == nil {
				v.Sources[i].PluginDesktop = source.ProviderID == "doubao-work"
				v.Sources[i].PluginDesktopUnavailable = modelplugins.DesktopUnavailable(source.ProviderID)
				if provider, err := s.plugins.CachedProvider(source); err == nil {
					v.Sources[i].HasKey = provider.SignedIn
					accounts := len(provider.Accounts)
					v.Sources[i].AccountRoutingAvailable = accounts > 1 && accounts <= routing.MaxSourceAccounts && routing.PluginSignedIn(provider)
				}
			}
		}
	}
	v.Token = ""
	return v
}
func (s *CatalogStore) validatedSource(p ModelSource, previous ModelSource) (ModelSource, error) {
	key, err := modelcatalog.SourceKey(p.SourceKey, previous.SourceKey)
	if err != nil {
		return ModelSource{}, err
	}
	p.SourceKey = key
	if p.Connector != "" && (p.Connector != openRouterFreeConnector || p.PluginSourceID != "") {
		return ModelSource{}, catalogError()
	}
	if p.PluginSourceID != "" {
		if len(p.Headers) > 0 || s.plugins == nil || p.ID != p.PluginSourceID || strings.TrimSpace(p.Name) == "" || len(p.Name) > 200 || strings.ContainsAny(p.Name, "\r\n\x00") {
			return ModelSource{}, catalogError()
		}
		if _, err := s.plugins.ReadSource(p.PluginSourceID); err != nil {
			return ModelSource{}, catalogError()
		}
		if previous.ID != "" && previous.PluginSourceID != p.PluginSourceID {
			return ModelSource{}, catalogError()
		}
		return ModelSource{ID: p.ID, PluginSourceID: p.PluginSourceID, PluginRevision: previous.PluginRevision, Name: strings.TrimSpace(p.Name), SourceKey: p.SourceKey, BaseURL: "https://magpie.invalid/" + p.ID, Protocol: "openai-completions", AuthMode: "plugin"}, nil
	}
	if previous.PluginSourceID != "" {
		return ModelSource{}, catalogError()
	}

	p, err = modelcatalog.NormalizeHTTPSource(p)
	if err != nil {
		return ModelSource{}, err
	}
	if s.isGatewaySource(p.BaseURL) {
		return ModelSource{}, catalogError()
	}
	return modelcatalog.ResolveCredentials(p, previous)
}

func (s *CatalogStore) update(ctx context.Context, v ModelCatalog) error {
	if s.applying || v.Revision != s.value.Revision {
		return errors.New("MODEL_CATALOG_CHANGED")
	}
	if len(v.Sources) > 64 || len(v.Models) > 1000 || len(v.Drafts) > 200 {
		return catalogError()
	}
	previous := map[string]ModelSource{}
	for _, p := range s.value.Sources {
		previous[p.ID] = p
	}
	sources := map[string]ModelSource{}
	sourceKeys := map[string]bool{}
	for i := range v.Sources {
		p := &v.Sources[i]
		validated, err := s.validatedSource(*p, previous[p.ID])
		if err != nil {
			return err
		}
		if _, exists := sources[p.ID]; exists {
			return catalogError()
		}
		if validated.SourceKey != nil {
			key := *validated.SourceKey
			if sourceKeys[key] {
				return modelcatalog.ErrDuplicateSourceKey
			}
			sourceKeys[key] = true
		}
		*p = validated
		sources[p.ID] = *p
	}
	modelcatalog.AssignSourceKeys(v.Sources)
	if err := modelcatalog.ValidateModels(v.Models, sources); err != nil {
		return err
	}
	if err := modelcatalog.ValidateAliases(s.value.Models, v.Models); err != nil {
		return err
	}
	modelcatalog.CanonicalizeGroups(v.Models, v.Drafts)
	if err := modelcatalog.ValidateRoutingGraph(v.Models); err != nil {
		return err
	}
	if err := modelcatalog.ValidateModels(v.Drafts, sources); err != nil {
		return err
	}
	uses, known := s.references(ctx)
	previousNames, nextNames := s.value.gatewayNames(), v.gatewayNames()
	for _, old := range s.value.Models {
		for _, id := range append([]string{old.ID}, old.AdditionalGatewayNames()...) {
			if modelcatalog.FindModel(v.Models, id) == nil && (!known || len(uses[id]) > 0) {
				return errors.New("MODEL_CATALOG_IN_USE")
			}
		}
		if name := previousNames.qualified[old.ID]; name != "" && (!known || len(uses[name]) > 0) {
			if i, ok := nextNames.owners[name]; !ok || !v.Models[i].MatchesGatewayName(old.ID) {
				return errors.New("MODEL_CATALOG_IN_USE")
			}
		}
	}
	v.Port = s.value.Port
	v.LANEnabled = s.value.LANEnabled
	v.Token = s.value.Token
	v.AccessKey = s.value.AccessKey
	v.AccessKeys = append([]gatewayAccessKey(nil), s.value.AccessKeys...)
	v.RolesBackup = s.value.RolesBackup
	v.AgentKeys = map[string]agentKeyState{}
	for kind, key := range s.value.AgentKeys {
		v.AgentKeys[kind] = key
	}
	v.BaseURL = ""
	v.Uses = nil
	v.DefaultModel = ""
	v.QualifiedModelIDs = nil
	if err := s.persist(v); err != nil {
		return err
	}
	if s.plugins != nil {
		for id, source := range previous {
			if _, retained := sources[id]; !retained && source.PluginSourceID != "" {
				s.plugins.Remove(source.PluginSourceID)
			}
		}
	}
	return nil
}
