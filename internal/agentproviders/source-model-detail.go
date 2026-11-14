package agentproviders

import (
	"math"
	"strconv"
	"strings"
)

// SourceModelDetail contains advertised properties, never inferred capabilities.
type SourceModelDetail struct {
	ID               string   `json:"id"`
	Name             string   `json:"name,omitempty"`
	Context          int      `json:"context,omitempty"`
	Output           int      `json:"output,omitempty"`
	InputModalities  []string `json:"inputModalities,omitempty"`
	OutputModalities []string `json:"outputModalities,omitempty"`
	Tools            *bool    `json:"tools,omitempty"`
	Reasoning        *bool    `json:"reasoning,omitempty"`
	InputPrice       *float64 `json:"inputPrice,omitempty"`
	OutputPrice      *float64 `json:"outputPrice,omitempty"`
}

type sourceModelWire struct {
	ID           string   `json:"id"`
	Name         string   `json:"name"`
	Context      int      `json:"context_length"`
	Parameters   []string `json:"supported_parameters"`
	Architecture struct {
		Input  []string `json:"input_modalities"`
		Output []string `json:"output_modalities"`
	} `json:"architecture"`
	TopProvider struct {
		Output int `json:"max_completion_tokens"`
	} `json:"top_provider"`
	Pricing struct {
		Input  string `json:"prompt"`
		Output string `json:"completion"`
	} `json:"pricing"`
}

func (m sourceModelWire) detail(id, secret string) SourceModelDetail {
	row := SourceModelDetail{ID: id}
	if len(m.Name) <= 200 && !strings.ContainsAny(m.Name, "\r\n\x00") && (secret == "" || !strings.Contains(m.Name, secret)) {
		row.Name = m.Name
	}
	if m.Context > 0 && m.Context <= 100000000 {
		row.Context = m.Context
	}
	if m.TopProvider.Output > 0 && m.TopProvider.Output <= 100000000 {
		row.Output = m.TopProvider.Output
	}
	modalities := func(values []string) []string {
		out := []string{}
		for _, allowed := range []string{"text", "image", "audio", "video", "file"} {
			for _, v := range values {
				if v == allowed {
					out = append(out, v)
					break
				}
			}
		}
		return out
	}
	row.InputModalities, row.OutputModalities = modalities(m.Architecture.Input), modalities(m.Architecture.Output)
	if m.Parameters != nil {
		tools, reasoning := false, false
		for _, p := range m.Parameters {
			tools = tools || p == "tools"
			reasoning = reasoning || p == "reasoning" || p == "reasoning_effort" || p == "include_reasoning"
		}
		row.Tools, row.Reasoning = &tools, &reasoning
	}
	price := func(raw string) *float64 {
		v, err := strconv.ParseFloat(raw, 64)
		v *= 1000000
		if err != nil || math.IsNaN(v) || math.IsInf(v, 0) || v < 0 || v > 100000000 {
			return nil
		}
		return &v
	}
	row.InputPrice, row.OutputPrice = price(m.Pricing.Input), price(m.Pricing.Output)
	return row
}
