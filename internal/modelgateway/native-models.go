package modelgateway

import (
	"github.com/ybz21/Roami/internal/agentproviders"
	"strings"
)

const gatewayDefaultModel = "roami-default"

func (s *CatalogStore) modelOptions(catalog ModelCatalog) []agentproviders.ModelOption {
	models := make([]agentproviders.ModelOption, 0, len(catalog.Models)+1)
	if s.defaultModel(catalog) != nil {
		models = append(models, agentproviders.ModelOption{ID: gatewayDefaultModel, Name: "Roami Default"})
	}
	for _, model := range catalog.Models {
		if model.Aggregate && !model.enabled() {
			continue
		}
		models = append(models, agentproviders.ModelOption{ID: model.ID, Name: model.Name})
	}
	return models
}

func codexModelCatalog(models []agentproviders.ModelOption) map[string]any {
	rows := make([]map[string]any, 0, len(models))
	for index, model := range models {
		rows = append(rows, map[string]any{
			"slug": model.ID, "display_name": model.Name,
			"base_instructions":          "Help the user with their coding tasks.",
			"supported_reasoning_levels": []any{}, "shell_type": "shell_command",
			"visibility": "list", "supported_in_api": true, "priority": index,
			"support_verbosity": false, "truncation_policy": map[string]any{"mode": "tokens", "limit": 10000},
			"experimental_supported_tools": []any{},
		})
	}
	return map[string]any{"models": rows}
}

func (s *CatalogStore) defaultModel(catalog ModelCatalog) *CatalogModel {
	route, err := readNodeModels(s.ledger.paths, "main")
	if err != nil {
		return nil
	}
	for _, model := range catalog.Models {
		if model.Aggregate && !model.enabled() {
			continue
		}
		if strings.TrimRight(route.endpoint, "/") == s.baseURL+"/v1" {
			if model.ID == route.model || containsField(model.Aliases, route.model) {
				return &model
			}
			continue
		}
		if model.Aggregate {
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
