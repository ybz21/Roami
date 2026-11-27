package service

import "strings"

const claudeModelPrefix = "roami-claude/"

// Claude's discovery keeps only IDs containing claude or anthropic.
func (c ModelCatalog) catalogModelID(kind, id string) string {
	if kind == "claude" {
		name := strings.TrimPrefix(id, claudeModelPrefix)
		if trimmed, suffix := strings.CutSuffix(name, "[1m]"); suffix && c.findGatewayModel(name) == nil {
			name = trimmed
		}
		if name != id && name != gatewayDefaultModel && c.findGatewayModel(name) == nil && c.findGatewayModel(id) != nil {
			return id
		}
		return name
	}
	return id
}
