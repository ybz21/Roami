package agentproviders

import "strings"

// Claude discovers gateway models only when their IDs contain its provider name.
func ClaudeGatewayModelID(model string) string {
	if model == "" || strings.HasPrefix(model, "roami-claude/") {
		return model
	}
	return "roami-claude/" + model
}

func NativeModelID(kind, model string, view View) string {
	if kind != "claude" || model == "" {
		return model
	}
	for _, profile := range view.Profiles {
		if profile.ID == view.ActiveID && profile.Name == "Roami Gateway" && profile.BaseURL == view.Current.BaseURL {
			return ClaudeGatewayModelID(model)
		}
	}
	return model
}
