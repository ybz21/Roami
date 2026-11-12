package modelgateway

import "strings"

const gatewayDefaultModel = "roami-default"
const claudeModelPrefix = "roami-claude/"

// Claude's discovery keeps only IDs containing claude or anthropic.
func catalogModelID(kind, id string) string {
	if kind == "claude" {
		return strings.TrimSuffix(strings.TrimPrefix(id, claudeModelPrefix), "[1m]")
	}
	return id
}

func (s *CatalogStore) defaultModel(catalog ModelCatalog) *CatalogModel {
	route, err := readNodeModels(s.ledger.paths, "main")
	if err != nil {
		return nil
	}
	for _, model := range catalog.Models {
		if strings.TrimRight(route.endpoint, "/") == s.baseURL+"/v1" {
			if model.ID == route.model {
				return &model
			}
			continue
		}
		for _, source := range catalog.Sources {
			if source.Protocol == "openai-completions" && strings.TrimRight(source.BaseURL, "/") == strings.TrimRight(route.endpoint, "/") && source.APIKey == route.key && model.Candidates[0] == (ModelCandidate{SourceID: source.ID, Model: route.model}) {
				return &model
			}
		}
	}
	return nil
}
