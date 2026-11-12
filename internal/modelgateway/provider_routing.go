package modelgateway

import (
	"crypto/sha256"
	"encoding/hex"
)

func providerRouteModel(candidate ModelCandidate, strategy string) CatalogModel {
	if strategy == "" {
		strategy = "smart"
	}
	sum := sha256.Sum256([]byte(candidateIdentity(candidate)))
	return CatalogModel{ID: "provider-" + hex.EncodeToString(sum[:]), Aggregate: true, Strategy: strategy, Candidates: []ModelCandidate{candidate}}
}
