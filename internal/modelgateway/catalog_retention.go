package modelgateway

import (
	"database/sql"
	"encoding/json"

	"github.com/ybz21/Roami/internal/modelgateway/storage"
)

func pruneCatalogRouting(tx *sql.Tx, catalog ModelCatalog) error {
	retained := map[string]bool{}
	for _, model := range catalog.Models {
		for _, candidate := range model.Candidates {
			if candidate.SourceID != groupSource {
				retained[providerRouteModel(candidate, "smart").ID] = true
			}
		}
		if model.Aggregate {
			retained[model.ID] = true
		}
	}
	if err := storage.PruneRouteAnchors(tx, retained); err != nil {
		return err
	}
	config, err := configuration(tx)
	if err != nil {
		return err
	}
	sources := map[string]bool{}
	for _, source := range catalog.Sources {
		sources[source.ID] = true
	}
	changed := false
	for id := range config.Pricing.Sources {
		if !sources[id] {
			delete(config.Pricing.Sources, id)
			changed = true
		}
	}
	if changed {
		raw, e := json.Marshal(config)
		if e != nil {
			return e
		}
		_, err = tx.Exec(`UPDATE gateway_configuration SET value=? WHERE id=1`, string(raw))
	}
	return err
}
