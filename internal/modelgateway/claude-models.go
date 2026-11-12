package modelgateway

import "strings"

const claudeModelPrefix = "roami-claude/"

// Claude's discovery keeps only IDs containing claude or anthropic.
func catalogModelID(kind, id string) string {
	if kind == "claude" {
		return strings.TrimSuffix(strings.TrimPrefix(id, claudeModelPrefix), "[1m]")
	}
	return id
}
