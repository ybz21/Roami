package directory

import (
	"slices"
	"sort"

	"github.com/ybz21/Roami/internal/agentproviders"
	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	"github.com/ybz21/Roami/internal/modelgateway/catalog"
)

type CapabilityFact struct {
	Support  string `json:"support"`
	Evidence string `json:"evidence"`
	Delivery string `json:"delivery"`
}
type Row struct {
	ID               string                    `json:"id"`
	Name             string                    `json:"name"`
	GatewayAlias     string                    `json:"gatewayAlias,omitempty"`
	GatewayHidden    bool                      `json:"gatewayHidden,omitempty"`
	Kind             string                    `json:"kind"`
	Protocol         string                    `json:"protocol"`
	Configured       bool                      `json:"configured"`
	Enabled          bool                      `json:"enabled"`
	FreeOnly         bool                      `json:"freeOnly"`
	ContextWindow    int                       `json:"contextWindow,omitempty"`
	MaxOutputTokens  int                       `json:"maxOutputTokens,omitempty"`
	InputModalities  []string                  `json:"inputModalities,omitempty"`
	OutputModalities []string                  `json:"outputModalities,omitempty"`
	InputPrice       *float64                  `json:"inputPrice,omitempty"`
	OutputPrice      *float64                  `json:"outputPrice,omitempty"`
	Pricing          string                    `json:"pricing"`
	Capabilities     map[string]CapabilityFact `json:"capabilities"`
	Candidates       []catalog.ModelCandidate  `json:"candidates"`
}

func unknownCapabilities() map[string]CapabilityFact {
	facts := map[string]CapabilityFact{}
	for _, name := range []string{"text", "image", "audio", "video", "tools", "reasoning", "structuredOutput", "streaming"} {
		facts[name] = CapabilityFact{"unknown", "unknown", "unknown"}
	}
	return facts
}
func advertisedCapabilities(detail agentproviders.SourceModelDetail) map[string]CapabilityFact {
	facts := unknownCapabilities()
	set := func(name string, value bool) {
		support := "unsupported"
		if value {
			support = "supported"
		}
		facts[name] = CapabilityFact{support, "advertised", "unknown"}
	}
	if len(detail.InputModalities) > 0 {
		for _, name := range []string{"text", "image", "audio", "video"} {
			set(name, slices.Contains(detail.InputModalities, name))
		}
	}
	for name, value := range map[string]*bool{"tools": detail.Tools, "reasoning": detail.Reasoning, "structuredOutput": detail.StructuredOutput} {
		if value != nil {
			set(name, *value)
		}
	}
	return facts
}
func Build(models []catalog.CatalogModel, sources []catalog.ModelSource, details map[catalog.ModelCandidate]agentproviders.SourceModelDetail, pluginFree map[catalog.ModelCandidate]bool, pricing accounting.PricingConfig, includeDiscovered bool) []Row {
	confirmedFree := func(candidate catalog.ModelCandidate) bool {
		if rule, exists := pricing.SourceRule(candidate.SourceID, candidate.Model); exists {
			return rule.Mode == "free" && rule.Confirmed
		}
		return pluginFree[candidate]
	}
	freeRoutePrice := func(id string) bool {
		price, overridden := pricing.MatchingPrice(id)
		return !overridden || price == (accounting.ModelPricing{})
	}
	byID := map[string]catalog.CatalogModel{}
	for _, model := range models {
		byID[model.ID] = model
	}
	var allMembersFree func(catalog.CatalogModel, int) bool
	freePools := map[string]bool{}
	allMembersFree = func(model catalog.CatalogModel, depth int) bool {
		if depth > 8 || len(model.Candidates) == 0 {
			return false
		}
		if result, seen := freePools[model.ID]; seen {
			return result
		}
		freePools[model.ID] = false
		for _, candidate := range model.Candidates {
			if candidate.SourceID == catalog.GroupSource {
				if !allMembersFree(byID[candidate.Model], depth+1) {
					return false
				}
			} else if !confirmedFree(candidate) {
				return false
			}
		}
		freePools[model.ID] = true
		return true
	}
	configured := map[catalog.ModelCandidate]bool{}
	rows := []Row{}
	hidden := catalog.HiddenGatewayMembers(models)
	for _, model := range models {
		kind := "single"
		if model.Aggregate {
			kind = "aggregate"
		}
		entry := Row{ID: model.ID, Name: model.Name, Kind: kind, Protocol: model.Protocol, Configured: true, Enabled: model.IsEnabled(), FreeOnly: model.FreeOnly, Pricing: "unknown", Capabilities: unknownCapabilities(), Candidates: model.Candidates}
		entry.GatewayAlias, entry.GatewayHidden = model.GatewayAlias, model.HiddenAtGateway(hidden)
		if model.FreeOnly {
			entry.Pricing = "free-only"
		} else if model.Aggregate && freeRoutePrice(model.ID) && allMembersFree(model, 0) {
			entry.Pricing = "confirmed-free"
		}
		if !model.Aggregate && len(model.Candidates) == 1 {
			candidate := model.Candidates[0]
			configured[candidate] = true
			if detail, ok := details[candidate]; ok {
				entry.Capabilities = advertisedCapabilities(detail)
				entry.ContextWindow, entry.MaxOutputTokens = detail.Context, detail.Output
				entry.InputModalities, entry.OutputModalities = detail.InputModalities, detail.OutputModalities
				entry.InputPrice, entry.OutputPrice = detail.InputPrice, detail.OutputPrice
				if detail.InputPrice != nil && detail.OutputPrice != nil && *detail.InputPrice == 0 && *detail.OutputPrice == 0 {
					entry.Pricing = "advertised-zero"
				} else if detail.InputPrice != nil && *detail.InputPrice > 0 || detail.OutputPrice != nil && *detail.OutputPrice > 0 {
					entry.Pricing = "metered"
				}
			}
			if confirmedFree(candidate) && freeRoutePrice(model.ID) {
				entry.Pricing = "confirmed-free"
			} else if rule, exists := pricing.SourceRule(candidate.SourceID, candidate.Model); exists && rule.Mode == "tokens" {
				entry.Pricing = "metered"
			}
		}
		// An aggregate's union is not a promise that the next selected member supports it.
		rows = append(rows, entry)
	}
	if includeDiscovered {
		for candidate, detail := range details {
			if configured[candidate] {
				continue
			}
			entry := Row{ID: candidate.Model, Name: detail.Name, Kind: "single", Pricing: "unknown", Capabilities: advertisedCapabilities(detail), Candidates: []catalog.ModelCandidate{candidate}, ContextWindow: detail.Context, MaxOutputTokens: detail.Output, InputModalities: detail.InputModalities, OutputModalities: detail.OutputModalities, InputPrice: detail.InputPrice, OutputPrice: detail.OutputPrice}
			entry.GatewayHidden = hidden[candidate]
			for _, source := range sources {
				if source.ID == candidate.SourceID {
					entry.Protocol = source.Protocol
				}
			}
			if detail.InputPrice != nil && detail.OutputPrice != nil && *detail.InputPrice == 0 && *detail.OutputPrice == 0 {
				entry.Pricing = "advertised-zero"
			} else if detail.InputPrice != nil && *detail.InputPrice > 0 || detail.OutputPrice != nil && *detail.OutputPrice > 0 {
				entry.Pricing = "metered"
			}
			rows = append(rows, entry)
		}
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].Configured != rows[j].Configured {
			return rows[i].Configured
		}
		if rows[i].Kind != rows[j].Kind {
			return rows[i].Kind == "aggregate"
		}
		return rows[i].ID < rows[j].ID
	})
	return rows
}
