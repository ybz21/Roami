package modelgateway

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/url"
	"regexp"
	"strings"
	"sync"

	"github.com/ybz21/Roami/internal/agentproviders"
)

type ModelSource struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	BaseURL  string `json:"baseUrl"`
	Protocol string `json:"protocol"`
	AuthMode string `json:"authMode"`
	APIKey   string `json:"apiKey,omitempty"`
	HasKey   bool   `json:"hasKey,omitempty"`
}
type ModelCandidate struct {
	SourceID string `json:"sourceId"`
	Model    string `json:"model"`
}
type CatalogModel struct {
	ID         string           `json:"id"`
	Name       string           `json:"name"`
	Protocol   string           `json:"protocol"`
	Strategy   string           `json:"strategy"`
	Candidates []ModelCandidate `json:"candidates"`
}
type ModelCatalog struct {
	Revision        string                   `json:"revision"`
	Sources         []ModelSource            `json:"sources"`
	Models          []CatalogModel           `json:"models"`
	Drafts          []CatalogModel           `json:"drafts"`
	BaseURL         string                   `json:"baseUrl,omitempty"`
	Uses            map[string][]string      `json:"uses"`
	Port            int                      `json:"-"`
	Token           string                   `json:"-"`
	RolesBackup     map[string]any           `json:"-"`
	AgentKeys       map[string]agentKeyState `json:"-"`
	CanRestoreRoami bool                     `json:"canRestoreRoami"`
	RoamiModels     map[string]string        `json:"roamiModels"`
}
type catalogDisk struct {
	Catalog     ModelCatalog             `json:"catalog"`
	Port        int                      `json:"port"`
	Token       string                   `json:"token"`
	RolesBackup map[string]any           `json:"rolesBackup,omitempty"`
	AgentKeys   map[string]agentKeyState `json:"agentKeys,omitempty"`
}
type CatalogStore struct {
	mu          sync.Mutex
	ledger      *Ledger
	value       ModelCatalog
	baseURL     string
	agents      *agentproviders.Store
	applying    bool
	agentSocket string
}

var catalogID = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$`)

func catalogError() error { return errors.New("INVALID_MODEL_CATALOG") }
func randomCatalogID() (string, error) {
	var b [24]byte
	if _, err := rand.Read(b[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(b[:]), nil
}
func openCatalog(l *Ledger) (*CatalogStore, error) {
	s := &CatalogStore{ledger: l, agents: agentproviders.NewStore(l.paths.Data)}
	var raw string
	err := l.db.QueryRow(`SELECT value FROM gateway_catalog WHERE id=1`).Scan(&raw)
	if err == nil {
		var d catalogDisk
		if json.Unmarshal([]byte(raw), &d) != nil || len(d.Token) != 48 || d.Port < 0 || d.Port > 65535 {
			return nil, catalogError()
		}
		s.value = d.Catalog
		s.value.Port = d.Port
		s.value.Token = d.Token
		s.value.RolesBackup = d.RolesBackup
		s.value.AgentKeys = d.AgentKeys
	} else if err == sql.ErrNoRows {
		token, e := randomCatalogID()
		if e != nil {
			return nil, e
		}
		s.value = ModelCatalog{Sources: []ModelSource{}, Models: []CatalogModel{}, Drafts: []CatalogModel{}, Token: token}
		if route, e := readNodeModels(l.paths, "main"); e == nil {
			s.value.Sources = append(s.value.Sources, ModelSource{ID: "existing", Name: route.endpoint, BaseURL: route.endpoint, Protocol: "openai-completions", AuthMode: "bearer", APIKey: route.key})
			s.value.Models = append(s.value.Models, CatalogModel{ID: "existing-main", Name: route.model, Protocol: "openai-completions", Strategy: "fixed", Candidates: []ModelCandidate{{"existing", route.model}}})
		}
		if e := s.persist(s.value); e != nil {
			return nil, e
		}
	} else {
		return nil, err
	}
	return s, nil
}
func (s *CatalogStore) persist(value ModelCatalog) error {
	revision, err := randomCatalogID()
	if err != nil {
		return err
	}
	value.Revision = revision
	// Suspend route evidence until the committed catalog and its fingerprints agree.
	if err := writeCatalogVerificationRevision(s.ledger.paths.Data, ModelCatalog{}); err != nil {
		return err
	}
	raw, err := json.Marshal(catalogDisk{Catalog: value, Port: value.Port, Token: value.Token, RolesBackup: value.RolesBackup, AgentKeys: value.AgentKeys})
	if err != nil {
		return err
	}
	err = s.ledger.db.Tx(func(tx *sql.Tx) error {
		_, e := tx.Exec(`INSERT INTO gateway_catalog(id,value) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value`, string(raw))
		return e
	})
	if err == nil {
		s.value = value
		err = writeCatalogVerificationRevision(s.ledger.paths.Data, value)
	}
	return err
}
func (s *CatalogStore) snapshot() ModelCatalog {
	raw, _ := json.Marshal(s.value)
	var v ModelCatalog
	_ = json.Unmarshal(raw, &v)
	v.Token = s.value.Token
	v.Port = s.value.Port
	v.RolesBackup = s.value.RolesBackup
	v.AgentKeys = map[string]agentKeyState{}
	for kind, key := range s.value.AgentKeys {
		v.AgentKeys[kind] = key
	}
	return v
}
func (s *CatalogStore) uses(ctx context.Context) map[string][]string {
	uses, _ := s.modelReferences(ctx, true)
	return uses
}
func (s *CatalogStore) references(ctx context.Context) (map[string][]string, bool) {
	return s.modelReferences(ctx, false)
}
func (s *CatalogStore) modelReferences(ctx context.Context, activeOnly bool) (map[string][]string, bool) {
	uses := map[string][]string{}
	known := true
	for _, role := range []string{"main", "worker"} {
		if route, err := readNodeModels(s.ledger.paths, role); err == nil && route.endpoint == s.baseURL+"/v1" {
			uses[route.model] = append(uses[route.model], "roami")
		}
	}
	for _, kind := range []string{"codex", "claude", "opencode", "pi"} {
		view, err := s.agents.View(ctx, kind)
		if err != nil {
			known = false
			continue
		}
		add := func(model string) {
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
	v.CanRestoreRoami = s.value.RolesBackup != nil
	v.RoamiModels = map[string]string{}
	for _, role := range []string{"main", "worker"} {
		if route, err := readNodeModels(s.ledger.paths, role); err == nil {
			v.RoamiModels[role] = route.model
		}
	}
	for i := range v.Sources {
		v.Sources[i].HasKey = v.Sources[i].APIKey != ""
		v.Sources[i].APIKey = ""
	}
	v.Token = ""
	return v
}
func (s *CatalogStore) validatedSource(p ModelSource, previous ModelSource) (ModelSource, error) {
	p.BaseURL = strings.TrimRight(strings.TrimSpace(p.BaseURL), "/")
	u, err := url.Parse(p.BaseURL)
	if !catalogID.MatchString(p.ID) || strings.TrimSpace(p.Name) == "" || len(p.Name) > 200 || len(p.BaseURL) > 2000 || err != nil || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || strings.ContainsAny(p.Name+p.BaseURL+p.APIKey, "\r\n\x00") {
		return ModelSource{}, catalogError()
	}
	if u.Scheme != "https" && !(u.Scheme == "http" && containsField([]string{"127.0.0.1", "localhost", "::1"}, u.Hostname())) {
		return ModelSource{}, catalogError()
	}
	if s.isGatewaySource(p.BaseURL) {
		return ModelSource{}, catalogError()
	}
	if !containsField([]string{"openai-completions", "openai-responses", "anthropic-messages"}, p.Protocol) || !containsField([]string{"api_key", "bearer"}, p.AuthMode) {
		return ModelSource{}, catalogError()
	}
	if p.APIKey == "" {
		old := previous
		if old.BaseURL != p.BaseURL && old.APIKey != "" {
			return ModelSource{}, errors.New("MODEL_KEY_REQUIRED_FOR_ENDPOINT")
		}
		p.APIKey = old.APIKey
	}
	if len(p.APIKey) > 8192 {
		return ModelSource{}, catalogError()
	}
	p.HasKey = false
	return p, nil
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
	for i := range v.Sources {
		p := &v.Sources[i]
		validated, err := s.validatedSource(*p, previous[p.ID])
		if err != nil {
			return err
		}
		if _, exists := sources[p.ID]; exists {
			return catalogError()
		}
		*p = validated
		sources[p.ID] = *p
	}
	validate := func(rows []CatalogModel) error {
		seen := map[string]bool{}
		for _, m := range rows {
			if !catalogID.MatchString(m.ID) || strings.TrimSpace(m.Name) == "" || len(m.Name) > 200 || seen[m.ID] || !containsField([]string{"fixed", "failover"}, m.Strategy) || len(m.Candidates) == 0 || len(m.Candidates) > 8 || m.Strategy == "fixed" && len(m.Candidates) != 1 || m.Strategy == "failover" && len(m.Candidates) < 2 {
				return catalogError()
			}
			seen[m.ID] = true
			for _, c := range m.Candidates {
				p, ok := sources[c.SourceID]
				if !ok || c.SourceID == m.Candidates[0].SourceID && p.Protocol != m.Protocol || c.Model == "" || len(c.Model) > 200 || strings.ContainsAny(c.Model, "\r\n\x00") {
					return catalogError()
				}
			}
		}
		return nil
	}
	if err := validate(v.Models); err != nil {
		return err
	}
	if err := validate(v.Drafts); err != nil {
		return err
	}
	uses, known := s.references(ctx)
	for _, old := range s.value.Models {
		retained := false
		for _, m := range v.Models {
			if m.ID == old.ID {
				retained = true
			}
		}
		if !retained && !known {
			return errors.New("MODEL_CATALOG_IN_USE")
		}
		if len(uses[old.ID]) > 0 {
			found := false
			for _, m := range v.Models {
				if m.ID == old.ID {
					found = true
				}
			}
			if !found {
				return errors.New("MODEL_CATALOG_IN_USE")
			}
		}
	}
	v.Port = s.value.Port
	v.Token = s.value.Token
	v.RolesBackup = s.value.RolesBackup
	v.AgentKeys = map[string]agentKeyState{}
	for kind, key := range s.value.AgentKeys {
		v.AgentKeys[kind] = key
	}
	v.BaseURL = ""
	v.Uses = nil
	return s.persist(v)
}
