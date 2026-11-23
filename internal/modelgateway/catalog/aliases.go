package catalog

import "slices"

func (m CatalogModel) MatchesGatewayName(id string) bool {
	return m.ID == id || (id != "" && m.GatewayAlias == id) || slices.Contains(m.Aliases, id)
}

func (m CatalogModel) PublicGatewayName() string {
	if m.GatewayAlias != "" {
		return m.GatewayAlias
	}
	return m.ID
}

func (m CatalogModel) AdditionalGatewayNames() []string {
	if m.GatewayAlias == "" {
		return m.Aliases
	}
	return append([]string{m.GatewayAlias}, m.Aliases...)
}

func FindModel(models []CatalogModel, id string) *CatalogModel {
	for i := range models {
		if models[i].MatchesGatewayName(id) {
			return &models[i]
		}
	}
	return nil
}

// Rename aliases must come from one existing model and retain its full identity history.
func ValidateAliases(previous, next []CatalogModel) error {
	seen := map[string]bool{}
	for _, model := range next {
		if len(model.Aliases) > 32 {
			return ErrInvalid
		}
		var owner *CatalogModel
		for _, id := range append([]string{model.ID}, model.Aliases...) {
			if !ValidID(id) || id == DefaultModelID || seen[id] {
				return ErrInvalid
			}
			seen[id] = true
			old := FindModel(previous, id)
			if old != nil && old.GatewayAlias == id && old.ID != model.ID && !slices.Contains(model.Aliases, old.ID) {
				return ErrInvalidAlias
			}
			if old != nil {
				if owner != nil && owner.ID != old.ID {
					return ErrInvalid
				}
				owner = old
			} else if id != model.ID {
				return ErrInvalid
			}
		}
		if owner != nil && (len(model.Aliases) > 0 || len(owner.Aliases) > 0) {
			if model.Aggregate != owner.Aggregate || model.Protocol != owner.Protocol {
				return ErrInvalid
			}
			for _, id := range append([]string{owner.ID}, owner.Aliases...) {
				if id != model.ID && !slices.Contains(model.Aliases, id) {
					return ErrInvalid
				}
			}
		}
	}
	for _, model := range next {
		alias := model.GatewayAlias
		if alias == "" {
			continue
		}
		if !ValidID(alias) || alias == DefaultModelID || seen[alias] {
			return ErrInvalidAlias
		}
		if old := FindModel(previous, alias); old != nil && old.ID != model.ID && !slices.Contains(model.Aliases, old.ID) {
			return ErrInvalidAlias
		}
		seen[alias] = true
	}
	return nil
}
