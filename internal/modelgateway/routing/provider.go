package routing

import (
	"crypto/sha256"
	"encoding/hex"

	"github.com/ybz21/Roami/internal/modelgateway/catalog"
)

func ProviderModel(candidate catalog.ModelCandidate, strategy string) catalog.CatalogModel {
	if strategy == "" {
		strategy = "smart"
	}
	sum := sha256.Sum256([]byte(candidate.Identity()))
	return catalog.CatalogModel{ID: "provider-" + hex.EncodeToString(sum[:]), Aggregate: true, Strategy: strategy, Candidates: []catalog.ModelCandidate{candidate}}
}
