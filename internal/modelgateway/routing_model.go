package modelgateway

import (
	"fmt"
	"strings"
)

var routingStrategies = []string{"smart", "order", "drain", "rotate", "usage", "pace", "weight", "fast", "cheap"}

const groupSource = "@group"

func candidateIdentity(c ModelCandidate) string { return c.SourceID + "/" + c.Model }
func (m CatalogModel) enabled() bool            { return m.Enabled == nil || *m.Enabled }
func (m CatalogModel) cooldown() int {
	if m.CooldownSeconds == 0 {
		return 60
	}
	return m.CooldownSeconds
}
func (m CatalogModel) switchLimit() bool     { return m.OnLimit == nil || *m.OnLimit }
func (m CatalogModel) switchExhausted() bool { return m.OnExhausted == nil || *m.OnExhausted }
func validateRoutingGraph(models []CatalogModel) error {
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
			return 0, catalogError()
		}
		path[id] = true
		defer delete(path, id)
		leaves := 0
		for _, candidate := range model.Candidates {
			if candidate.SourceID == groupSource {
				count, err := visit(candidate.Model, path, depth+1)
				if err != nil {
					return 0, err
				}
				leaves += count
			} else {
				leaves++
			}
			if leaves > 64 {
				return 0, catalogError()
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
	if !containsField([]string{"openai-completions", "openai-responses", "anthropic-messages"}, model.Protocol) || !containsField(routingStrategies, model.Strategy) || model.CooldownSeconds < 0 || model.CooldownSeconds > 3600 || model.MinContext < 0 || model.MinContext > 10000000 || len(model.Weights) > 8 {
		return false
	}
	seen := map[string]bool{}
	for _, candidate := range model.Candidates {
		key := candidateIdentity(candidate)
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
