package modelgateway

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
)

// Loopback URLs and aliases stay unchanged when an upstream credential or route changes.
func writeCatalogVerificationRevision(root string, catalog ModelCatalog) error {
	type route struct{ URL, Protocol, AuthMode, Credential, Model string }
	sources := map[string]ModelSource{}
	for _, source := range catalog.Sources {
		sources[source.ID] = source
	}
	fingerprints := map[string]string{}
	for _, model := range catalog.Models {
		routes := []route{}
		for _, candidate := range model.Candidates {
			source := sources[candidate.SourceID]
			routes = append(routes, route{source.BaseURL, source.Protocol, source.AuthMode, source.APIKey, candidate.Model})
		}
		raw, err := json.Marshal(struct {
			Protocol, Strategy string
			Routes             []route
		}{model.Protocol, model.Strategy, routes})
		if err != nil {
			return err
		}
		digest := sha256.Sum256(raw)
		fingerprints[model.ID] = hex.EncodeToString(digest[:])
	}
	directory := filepath.Join(root, "agents")
	if err := os.MkdirAll(directory, 0700); err != nil {
		return err
	}
	file, err := os.CreateTemp(directory, ".model-catalog-revision-")
	if err != nil {
		return err
	}
	defer os.Remove(file.Name())
	err = json.NewEncoder(file).Encode(fingerprints)
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(file.Name(), filepath.Join(directory, "model-catalog-revision"))
}
