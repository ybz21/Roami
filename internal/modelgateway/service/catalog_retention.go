package service

import (
	"database/sql"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	"github.com/ybz21/Roami/internal/modelgateway/routing"
	"github.com/ybz21/Roami/internal/modelgateway/storage"
)

func pruneCatalogRouting(tx *sql.Tx, catalog ModelCatalog) error {
	retained := map[string]bool{}
	for _, model := range catalog.Models {
		for _, candidate := range model.Candidates {
			if candidate.SourceID != groupSource {
				retained[routing.ProviderModel(candidate, "smart").ID] = true
			}
		}
		if model.Aggregate {
			retained[model.ID] = true
		}
	}
	if err := storage.PruneRouteAnchors(tx, retained); err != nil {
		return err
	}
	sources := map[string]bool{}
	for _, source := range catalog.Sources {
		sources[source.ID] = true
	}
	return accounting.PruneSourcePricing(tx, sources)
}
