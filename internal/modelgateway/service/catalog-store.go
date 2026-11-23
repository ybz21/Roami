package service

import (
	"database/sql"
	"encoding/json"

	"github.com/ybz21/Roami/internal/agentproviders"
	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/hostroute"
	"github.com/ybz21/Roami/internal/modelgateway/storage"
)

func openCatalog(l *gatewayState) (*CatalogStore, error) {
	s := &CatalogStore{state: l, agents: agentproviders.NewStore(l.paths.Data)}
	raw, err := storage.LoadCatalog(l.db)
	if err == nil {
		var d catalogDisk
		if json.Unmarshal([]byte(raw), &d) != nil || len(d.Token) != 48 || d.Port < 0 || d.Port > 65535 || !validStoredGatewayAccessKey(d.AccessKey) || !validStoredGatewayAccessKeys(d.AccessKeys) {
			return nil, catalogError()
		}
		s.value = d.Catalog
		s.value.Port = d.Port
		s.value.LANEnabled = d.LANEnabled
		s.value.Token = d.Token
		s.value.AccessKey = d.AccessKey
		s.value.AccessKeys = d.AccessKeys
		s.value.RolesBackup = d.RolesBackup
		s.value.AgentKeys = d.AgentKeys
		if modelcatalog.AssignSourceKeys(s.value.Sources) {
			if err := s.persist(s.value); err != nil {
				return nil, err
			}
		}
	} else if err == sql.ErrNoRows {
		token, e := randomCatalogID()
		if e != nil {
			return nil, e
		}
		s.value = ModelCatalog{Sources: []ModelSource{}, Models: []CatalogModel{}, Drafts: []CatalogModel{}, Token: token}
		if route, e := hostroute.Read(l.paths, "main"); e == nil {
			s.value.Sources = append(s.value.Sources, ModelSource{ID: "existing", Name: route.Endpoint, BaseURL: route.Endpoint, Protocol: "openai-completions", AuthMode: "bearer", APIKey: route.Key})
			s.value.Models = append(s.value.Models, CatalogModel{ID: "existing-main", Name: route.Model, Protocol: "openai-completions", Strategy: "fixed", Candidates: []ModelCandidate{{"existing", route.Model}}})
		}
		modelcatalog.AssignSourceKeys(s.value.Sources)
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
	if err := writeCatalogVerificationRevision(s.state.paths.Data, ModelCatalog{}); err != nil {
		return err
	}
	raw, err := json.Marshal(catalogDisk{Catalog: value, Port: value.Port, LANEnabled: value.LANEnabled, Token: value.Token, RolesBackup: value.RolesBackup, AgentKeys: value.AgentKeys, AccessKey: value.AccessKey, AccessKeys: value.AccessKeys})
	if err != nil {
		return err
	}
	err = storage.SaveCatalog(s.state.db, raw, func(tx *sql.Tx) error {
		return pruneCatalogRouting(tx, value)
	})
	if err == nil {
		s.value = value
		err = writeCatalogVerificationRevision(s.state.paths.Data, value)
	}
	return err
}
func (s *CatalogStore) snapshot() ModelCatalog {
	raw, _ := json.Marshal(s.value)
	var v ModelCatalog
	_ = json.Unmarshal(raw, &v)
	// Aggregate member filtering must not become a request cost policy.
	for _, models := range [][]CatalogModel{v.Models, v.Drafts} {
		for i := range models {
			if models[i].Aggregate {
				models[i].FreeOnly = false
				models[i].AllowPlan = false
			}
		}
	}
	v.Token = s.value.Token
	v.AccessKey = s.value.AccessKey
	v.AccessKeys = append([]gatewayAccessKey(nil), s.value.AccessKeys...)
	v.Port = s.value.Port
	v.LANEnabled = s.value.LANEnabled
	v.RolesBackup = s.value.RolesBackup
	v.AgentKeys = map[string]agentKeyState{}
	for kind, key := range s.value.AgentKeys {
		v.AgentKeys[kind] = key
	}
	return v
}
