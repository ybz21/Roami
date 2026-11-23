package catalog

import (
	"errors"
	"net/url"
	"slices"
	"strings"
)

func NormalizeHTTPSource(p ModelSource) (ModelSource, error) {
	p.BaseURL = strings.TrimRight(strings.TrimSpace(p.BaseURL), "/")
	if p.Connector == OpenRouterFreeConnector && (p.BaseURL != OpenRouterBaseURL || p.Protocol != "openai-completions" || p.AuthMode != "bearer") {
		return ModelSource{}, ErrInvalid
	}
	u, err := url.Parse(p.BaseURL)
	if !ValidID(p.ID) || strings.TrimSpace(p.Name) == "" || len(p.Name) > 200 || len(p.BaseURL) > 2000 || err != nil || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || strings.ContainsAny(p.Name+p.BaseURL+p.APIKey, "\r\n\x00") {
		return ModelSource{}, ErrInvalid
	}
	if u.Scheme != "https" && u.Scheme != "http" || p.SkipTLSVerification && u.Scheme != "https" {
		return ModelSource{}, ErrInvalid
	}
	if !slices.Contains([]string{"openai-completions", "openai-responses", "anthropic-messages"}, p.Protocol) || !slices.Contains([]string{"api_key", "bearer"}, p.AuthMode) {
		return ModelSource{}, ErrInvalid
	}
	return p, nil
}

func ResolveCredentials(p, previous ModelSource) (ModelSource, error) {
	if p.APIKey == "" {
		old := previous
		if old.BaseURL != p.BaseURL && old.APIKey != "" {
			return ModelSource{}, errors.New("MODEL_KEY_REQUIRED_FOR_ENDPOINT")
		}
		p.APIKey = old.APIKey
	}
	if len(p.APIKey) > 8192 {
		return ModelSource{}, ErrInvalid
	}
	headers, err := validateSourceHeaders(p, previous)
	if err != nil {
		return ModelSource{}, err
	}
	p.Headers = headers
	p.HeaderNames = nil
	p.HasKey = false
	p.AccountRoutingAvailable = false
	return p, nil
}
