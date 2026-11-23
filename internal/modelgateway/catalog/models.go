// Package catalog defines model configuration and publication rules.
package catalog

import (
	"errors"
	"regexp"
)

const (
	GroupSource             = "@group"
	DefaultModelID          = "roami-default"
	MaxAggregateMembers     = 64
	OpenRouterFreeConnector = "openrouter-free"
	OpenRouterBaseURL       = "https://openrouter.ai/api/v1"
)

var (
	ErrInvalid            = errors.New("INVALID_MODEL_CATALOG")
	ErrSourceKeyRequired  = errors.New("MODEL_SOURCE_KEY_REQUIRED")
	ErrInvalidSourceKey   = errors.New("INVALID_MODEL_SOURCE_KEY")
	ErrDuplicateSourceKey = errors.New("MODEL_SOURCE_KEY_IN_USE")
	ErrInvalidAlias       = errors.New("INVALID_MODEL_GATEWAY_ALIAS")
	idPattern             = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$`)
)

func ValidID(id string) bool { return idPattern.MatchString(id) }

type ModelSource struct {
	ID                       string            `json:"id"`
	Connector                string            `json:"connector,omitempty"`
	PluginSourceID           string            `json:"pluginSourceId,omitempty"`
	PluginRevision           string            `json:"pluginRevision,omitempty"`
	PluginDesktop            bool              `json:"pluginDesktop,omitempty"`
	PluginDesktopUnavailable bool              `json:"pluginDesktopUnavailable,omitempty"`
	AccountRoutingAvailable  bool              `json:"accountRoutingAvailable,omitempty"`
	Name                     string            `json:"name"`
	SourceKey                *string           `json:"sourceKey,omitempty"`
	BaseURL                  string            `json:"baseUrl"`
	Protocol                 string            `json:"protocol"`
	AuthMode                 string            `json:"authMode"`
	SkipTLSVerification      bool              `json:"skipTlsVerification,omitempty"`
	APIKey                   string            `json:"apiKey,omitempty"`
	HasKey                   bool              `json:"hasKey,omitempty"`
	Headers                  map[string]string `json:"headers,omitempty"`
	HeaderNames              []string          `json:"headerNames,omitempty"`
}
type ModelCandidate struct {
	SourceID string `json:"sourceId"`
	Model    string `json:"model"`
}
type CatalogModel struct {
	Aggregate       bool             `json:"aggregate,omitempty"`
	HideMembers     bool             `json:"hideMembers,omitempty"`
	GatewayHidden   bool             `json:"gatewayHidden,omitempty"`
	Enabled         *bool            `json:"enabled,omitempty"`
	FreeOnly        bool             `json:"freeOnly,omitempty"`
	AllowPlan       bool             `json:"allowPlan,omitempty"`
	RequireTools    bool             `json:"requireTools,omitempty"`
	MinContext      int              `json:"minContext,omitempty"`
	CooldownSeconds int              `json:"cooldownSeconds,omitempty"`
	OnLimit         *bool            `json:"onLimit,omitempty"`
	OnExhausted     *bool            `json:"onExhausted,omitempty"`
	Weights         map[string]int   `json:"weights,omitempty"`
	ID              string           `json:"id"`
	Aliases         []string         `json:"aliases,omitempty"`
	GatewayAlias    string           `json:"gatewayAlias,omitempty"`
	Name            string           `json:"name"`
	Protocol        string           `json:"protocol"`
	Strategy        string           `json:"strategy"`
	Candidates      []ModelCandidate `json:"candidates"`
}
