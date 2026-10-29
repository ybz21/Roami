// Adapted from llm-gateway/internal/observe/pricing.go at 1f1ffc1ab080c0da935d063ac79380d2f2a4a079.
package modelgateway

import "strings"

// ModelPricing 单个模型的 token 单价（元/百万 token）。
type ModelPricing struct {
	InputPerMillion     float64 `yaml:"input_per_million" json:"input_per_million"`
	OutputPerMillion    float64 `yaml:"output_per_million" json:"output_per_million"`
	CacheReadPerMillion float64 `yaml:"cache_read_per_million" json:"cache_read_per_million"`
}

// PricingConfig 计费配置。
type PricingConfig struct {
	Default ModelPricing            `yaml:"default" json:"default"`
	Models  map[string]ModelPricing `yaml:"models" json:"models"`
}

// lookup 返回某模型名的配置价格（精确 → 前缀），以及是否命中。
func (pc *PricingConfig) lookup(model string) (ModelPricing, bool) {
	if pc == nil || model == "" {
		return ModelPricing{}, false
	}
	if p, ok := pc.Models[model]; ok {
		return p, true
	}
	var price ModelPricing
	longest := 0
	for pattern, p := range pc.Models {
		if len(pattern) > longest && strings.HasPrefix(model, pattern) {
			price, longest = p, len(pattern)
		}
	}
	return price, longest > 0
}

// Lookup 查找模型价格：model 精确 → 前缀匹配 → default。
func (pc *PricingConfig) Lookup(model string) ModelPricing {
	if pc == nil {
		return ModelPricing{}
	}
	if p, ok := pc.lookup(model); ok {
		return p
	}
	return pc.Default
}

// LookupRoute 按 source_id/model 维度查找价格，找不到再按 model 维度回退。
func (pc *PricingConfig) LookupRoute(sourceID, model string) ModelPricing {
	if pc == nil {
		return ModelPricing{}
	}
	if sourceID != "" {
		if p, ok := pc.Models[sourceID+"/"+model]; ok {
			return p
		}
	}
	return pc.Lookup(model)
}

// LookupExit 按「出口模型」(客户端请求的对外模型名) 定价：聚合模型无论被哪个
// 上游承接，都按同一个对外名计价。出口名没有配置价格时，回退到 source/native
// 维度。这样客户付的是「广告出去的模型」的价，而不是内部路由到的具体源。
func (pc *PricingConfig) LookupExit(requested, sourceID, native string) ModelPricing {
	if pc == nil {
		return ModelPricing{}
	}
	if p, ok := pc.lookup(requested); ok {
		return p
	}
	return pc.LookupRoute(sourceID, native)
}

func calc(p ModelPricing, inputTokens, outputTokens, cacheReadTokens int) float64 {
	cost := float64(inputTokens) * p.InputPerMillion / 1_000_000
	cost += float64(outputTokens) * p.OutputPerMillion / 1_000_000
	cost += float64(cacheReadTokens) * p.CacheReadPerMillion / 1_000_000
	return cost
}

// CalcCost 计算单次调用费用（元）。
func (pc *PricingConfig) CalcCost(model string, inputTokens, outputTokens, cacheReadTokens int) float64 {
	return pc.CalcCostRoute("", model, inputTokens, outputTokens, cacheReadTokens)
}

// CalcCostRoute 按 source/model 维度计算费用。
func (pc *PricingConfig) CalcCostRoute(sourceID, model string, inputTokens, outputTokens, cacheReadTokens int) float64 {
	if pc == nil {
		return 0
	}
	return calc(pc.LookupRoute(sourceID, model), inputTokens, outputTokens, cacheReadTokens)
}

// CalcCostExit 按出口（对外请求）模型计费，回退到 source/native。
func (pc *PricingConfig) CalcCostExit(requested, sourceID, native string, inputTokens, outputTokens, cacheReadTokens int) float64 {
	if pc == nil {
		return 0
	}
	return calc(pc.LookupExit(requested, sourceID, native), inputTokens, outputTokens, cacheReadTokens)
}
