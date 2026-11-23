package catalog

func HiddenGatewayMembers(models []CatalogModel) map[ModelCandidate]bool {
	byID := make(map[string]CatalogModel, len(models))
	for _, model := range models {
		if model.Aggregate {
			byID[model.ID] = model
		}
	}
	hidden := map[ModelCandidate]bool{}
	visited := map[string]bool{}
	var hide func(CatalogModel)
	hide = func(model CatalogModel) {
		if visited[model.ID] {
			return
		}
		visited[model.ID] = true
		for _, member := range model.Candidates {
			if member.SourceID != GroupSource {
				hidden[member] = true
			} else if group, ok := byID[member.Model]; ok {
				hide(group)
			}
		}
	}
	for _, model := range models {
		if model.Aggregate && model.HideMembers {
			hide(model)
		}
	}
	return hidden
}

func (m CatalogModel) HiddenAtGateway(members map[ModelCandidate]bool) bool {
	if m.Aggregate {
		return false
	}
	for _, candidate := range m.Candidates {
		if members[candidate] {
			return true
		}
	}
	return false
}
