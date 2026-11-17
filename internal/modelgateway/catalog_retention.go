package modelgateway

import (
	"database/sql"
	"encoding/json"
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
	rows, err := tx.Query(`SELECT model_id FROM gateway_route_anchors`)
	if err != nil {
		return err
	}
	remove := []string{}
	for rows.Next() {
		var id string
		if err = rows.Scan(&id); err != nil {
			rows.Close()
			return err
		}
		if !retained[id] {
			remove = append(remove, id)
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return err
	}
	for _, id := range remove {
		if _, err = tx.Exec(`DELETE FROM gateway_route_anchors WHERE model_id=?`, id); err != nil {
			return err
		}
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
