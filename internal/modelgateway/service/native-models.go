package service

import (
	"strings"

	"github.com/ybz21/Roami/internal/agentproviders"
	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
	"github.com/ybz21/Roami/internal/modelgateway/hostroute"
)

const gatewayDefaultModel = modelcatalog.DefaultModelID

func (s *CatalogStore) modelOptions(catalog ModelCatalog) []agentproviders.ModelOption {
	models := make([]agentproviders.ModelOption, 0, len(catalog.Models)+1)
	if s.defaultModel(catalog) != nil {
		models = append(models, agentproviders.ModelOption{ID: gatewayDefaultModel, Name: "Roami Default"})
	}
	hidden := modelcatalog.HiddenGatewayMembers(catalog.Models)
	names := catalog.gatewayNames()
	for _, model := range catalog.Models {
		if (model.Aggregate && !model.IsEnabled()) || model.HiddenAtGateway(hidden) {
			continue
		}
		models = append(models, agentproviders.ModelOption{ID: names.publicName(model), Name: model.Name})
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
	route, err := hostroute.Read(s.state.paths, "main")
	if err != nil {
		return nil
	}
	hidden := modelcatalog.HiddenGatewayMembers(catalog.Models)
	if strings.TrimRight(route.Endpoint, "/") == s.baseURL+"/v1" {
		model := catalog.findGatewayModel(route.Model)
		if model != nil && (!model.Aggregate || model.IsEnabled()) && !model.HiddenAtGateway(hidden) {
			return model
		}
		return nil
	}
	for _, model := range catalog.Models {
		if model.Aggregate || model.HiddenAtGateway(hidden) {
			continue
		}
		for _, source := range catalog.Sources {
			if source.Protocol == "openai-completions" && strings.TrimRight(source.BaseURL, "/") == strings.TrimRight(route.Endpoint, "/") && source.APIKey == route.Key && model.Candidates[0] == (ModelCandidate{SourceID: source.ID, Model: route.Model}) {
				return &model
			}
		}
	}
	return nil
}
