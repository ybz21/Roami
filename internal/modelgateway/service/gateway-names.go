package service

import (
	"slices"
	"strings"

	modelcatalog "github.com/ybz21/Roami/internal/modelgateway/catalog"
)

type gatewayNames struct {
	qualified map[string]string
	owners    map[string]int
}

func (c ModelCatalog) gatewayNames() gatewayNames {
	sources := make(map[string]ModelSource, len(c.Sources))
	for _, source := range c.Sources {
		sources[source.ID] = source
	}
	names := gatewayNames{qualified: map[string]string{}, owners: map[string]int{}}
	for i, model := range c.Models {
		if model.Aggregate || len(model.Candidates) != 1 {
			continue
		}
		candidate := model.Candidates[0]
		source := sources[candidate.SourceID]
		if source.SourceKey == nil || *source.SourceKey == "" || candidate.Model == source.APIKey {
			continue
		}
		// Native clients interpret these placeholders when reading the model catalog.
		if strings.TrimSpace(candidate.Model) != candidate.Model || strings.Contains(candidate.Model, "{env:") || strings.Contains(candidate.Model, "{file:") {
			continue
		}
		name := *source.SourceKey + "/" + candidate.Model
		// Several saved routes can point to the same upstream. The first owns its qualified name.
		if _, taken := names.owners[name]; taken {
			continue
		}
		names.owners[name] = i
		names.qualified[model.ID] = name
	}
	return names
}

func (n gatewayNames) publicName(model CatalogModel) string {
	if model.GatewayAlias != "" {
		return model.GatewayAlias
	}
	if name := n.qualified[model.ID]; name != "" {
		return name
	}
	return model.ID
}

func (n gatewayNames) additionalNames(model CatalogModel) []string {
	names := model.AdditionalGatewayNames()
	if name := n.qualified[model.ID]; name != "" {
		return append(slices.Clone(names), name)
	}
	return names
}

func (c ModelCatalog) findGatewayModel(name string) *CatalogModel {
	if strings.Contains(name, "/") {
		if index, ok := c.gatewayNames().owners[name]; ok {
			return &c.Models[index]
		}
		return nil
	}
	return modelcatalog.FindModel(c.Models, name)
}
