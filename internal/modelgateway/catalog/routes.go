package catalog

import (
	"fmt"
	"slices"
	"strings"
)

var routingStrategies = []string{"smart", "order", "drain", "rotate", "usage", "pace", "weight", "fast", "cheap"}

func (c ModelCandidate) Identity() string { return c.SourceID + "/" + c.Model }
func (m CatalogModel) IsEnabled() bool    { return m.Enabled == nil || *m.Enabled }
func (m CatalogModel) Cooldown() int {
	if m.CooldownSeconds == 0 {
		return 60
	}
	return m.CooldownSeconds
}
func (m CatalogModel) SwitchOnLimit() bool     { return m.OnLimit == nil || *m.OnLimit }
func (m CatalogModel) SwitchOnExhausted() bool { return m.OnExhausted == nil || *m.OnExhausted }

func ValidateRoutingGraph(models []CatalogModel) error {
	byID := map[string]CatalogModel{}
	for _, model := range models {
		byID[model.ID] = model
	}
	var visit func(string, map[string]bool, int) (int, error)
	visit = func(id string, path map[string]bool, depth int) (int, error) {
		if depth > 8 || path[id] {
			return 0, fmt.Errorf("MODEL_ROUTE_CYCLE")
		}
		model, ok := byID[id]
		if !ok {
			return 0, ErrInvalid
		}
		path[id] = true
		defer delete(path, id)
		leaves := 0
		for _, candidate := range model.Candidates {
			if candidate.SourceID == GroupSource {
				count, err := visit(candidate.Model, path, depth+1)
				if err != nil {
					return 0, err
				}
				leaves += count
			} else {
				leaves++
			}
			if leaves > 64 {
				return 0, ErrInvalid
			}
		}
		return leaves, nil
	}
	for _, model := range models {
		if _, err := visit(model.ID, map[string]bool{}, 0); err != nil {
			return err
		}
	}
	return nil
}
func validateAggregate(model CatalogModel) bool {
	if !slices.Contains([]string{"openai-completions", "openai-responses", "anthropic-messages"}, model.Protocol) || !slices.Contains(routingStrategies, model.Strategy) || model.CooldownSeconds < 0 || model.CooldownSeconds > 3600 || model.MinContext < 0 || model.MinContext > 10000000 || len(model.Weights) > MaxAggregateMembers {
		return false
	}
	seen := map[string]bool{}
	for _, candidate := range model.Candidates {
		key := candidate.Identity()
		if seen[key] {
			return false
		}
		seen[key] = true
		if weight, ok := model.Weights[key]; ok && (weight < 1 || weight > 1000) {
			return false
		}
	}
	for key := range model.Weights {
		if !seen[key] || strings.ContainsAny(key, "\r\n\x00") {
			return false
		}
	}
	return true
}

func ValidateModels(rows []CatalogModel, sources map[string]ModelSource) error {
	seen := map[string]bool{}
	for i, m := range rows {
		rows[i].GatewayHidden = false
		if m.HideMembers && !m.Aggregate {
			return ErrInvalid
		}
		limit := 8
		if m.Aggregate {
			limit = MaxAggregateMembers
		}
		if !ValidID(m.ID) || m.ID == DefaultModelID || strings.TrimSpace(m.Name) == "" || len(m.Name) > 200 || seen[m.ID] || !(m.Aggregate && validateAggregate(m) || !m.Aggregate && slices.Contains([]string{"fixed", "failover"}, m.Strategy)) || len(m.Candidates) == 0 || len(m.Candidates) > limit || m.Strategy == "fixed" && len(m.Candidates) != 1 || m.Strategy == "failover" && len(m.Candidates) < 2 {
			return ErrInvalid
		}
		seen[m.ID] = true
		for _, c := range m.Candidates {
			if c.SourceID == GroupSource {
				if !m.Aggregate || !ValidID(c.Model) {
					return ErrInvalid
				}
				continue
			}
			p, ok := sources[c.SourceID]
			if !ok || !m.Aggregate && c.SourceID == m.Candidates[0].SourceID && p.Protocol != m.Protocol || c.Model == "" || len(c.Model) > 200 || strings.ContainsAny(c.Model, "\r\n\x00") {
				return ErrInvalid
			}
		}
	}
	return nil
}

func CanonicalizeGroups(models, drafts []CatalogModel) {
	// Store group references canonically, including references in saved drafts.
	for _, rows := range [][]CatalogModel{models, drafts} {
		for i := range rows {
			for j, candidate := range rows[i].Candidates {
				if candidate.SourceID == GroupSource {
					if model := FindModel(models, candidate.Model); model != nil {
						rows[i].Candidates[j].Model = model.ID
					}
				}
			}
		}
	}
}
