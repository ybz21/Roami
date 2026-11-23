package modelgateway

import "errors"

func (m CatalogModel) matchesGatewayName(id string) bool {
	return m.ID == id || (id != "" && m.GatewayAlias == id) || containsField(m.Aliases, id)
}

func (m CatalogModel) publicGatewayName() string {
	if m.GatewayAlias != "" {
		return m.GatewayAlias
	}
	return m.ID
}

func (m CatalogModel) additionalGatewayNames() []string {
	if m.GatewayAlias == "" {
		return m.Aliases
	}
	return append([]string{m.GatewayAlias}, m.Aliases...)
}

func findCatalogModel(models []CatalogModel, id string) *CatalogModel {
	for i := range models {
		if models[i].matchesGatewayName(id) {
			return &models[i]
		}
	}
	return nil
}

// Rename aliases must come from one existing model and retain its full identity history.
func validateModelAliases(previous, next []CatalogModel) error {
	seen := map[string]bool{}
	for _, model := range next {
		if len(model.Aliases) > 32 {
			return catalogError()
		}
		var owner *CatalogModel
		for _, id := range append([]string{model.ID}, model.Aliases...) {
			if !catalogID.MatchString(id) || id == gatewayDefaultModel || seen[id] {
				return catalogError()
			}
			seen[id] = true
			old := findCatalogModel(previous, id)
			if old != nil && old.GatewayAlias == id && old.ID != model.ID && !containsField(model.Aliases, old.ID) {
				return errors.New("INVALID_MODEL_GATEWAY_ALIAS")
			}
			if old != nil {
				if owner != nil && owner.ID != old.ID {
					return catalogError()
				}
				owner = old
			} else if id != model.ID {
				return catalogError()
			}
		}
		if owner != nil && (len(model.Aliases) > 0 || len(owner.Aliases) > 0) {
			if model.Aggregate != owner.Aggregate || model.Protocol != owner.Protocol {
				return catalogError()
			}
			for _, id := range append([]string{owner.ID}, owner.Aliases...) {
				if id != model.ID && !containsField(model.Aliases, id) {
					return catalogError()
				}
			}
		}
	}
	for _, model := range next {
		alias := model.GatewayAlias
		if alias == "" {
			continue
		}
		if !catalogID.MatchString(alias) || alias == gatewayDefaultModel || seen[alias] {
			return errors.New("INVALID_MODEL_GATEWAY_ALIAS")
		}
		if old := findCatalogModel(previous, alias); old != nil && old.ID != model.ID && !containsField(model.Aliases, old.ID) {
			return errors.New("INVALID_MODEL_GATEWAY_ALIAS")
		}
		seen[alias] = true
	}
	return nil
}
