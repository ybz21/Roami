package modelgateway

func findCatalogModel(models []CatalogModel, id string) *CatalogModel {
	for i := range models {
		if models[i].ID == id || containsField(models[i].Aliases, id) {
			return &models[i]
		}
	}
	return nil
}

// Rename aliases must come from one existing aggregate and retain its full identity history.
func validateModelAliases(previous, next []CatalogModel) error {
	seen := map[string]bool{}
	for _, model := range next {
		if len(model.Aliases) > 32 || len(model.Aliases) > 0 && !model.Aggregate {
			return catalogError()
		}
		var owner *CatalogModel
		for _, id := range append([]string{model.ID}, model.Aliases...) {
			if !catalogID.MatchString(id) || id == gatewayDefaultModel || seen[id] {
				return catalogError()
			}
			seen[id] = true
			old := findCatalogModel(previous, id)
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
			if !owner.Aggregate || model.Protocol != owner.Protocol {
				return catalogError()
			}
			for _, id := range append([]string{owner.ID}, owner.Aliases...) {
				if id != model.ID && !containsField(model.Aliases, id) {
					return catalogError()
				}
			}
		}
	}
	return nil
}
