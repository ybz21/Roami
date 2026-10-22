package agentproviders

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/ybz21/Roami/internal/agent"
)

type Profile struct {
	ID              string `json:"id"`
	Name            string `json:"name"`
	BaseURL         string `json:"baseUrl"`
	Model           string `json:"model"`
	Protocol        string `json:"protocol"`
	AuthMode        string `json:"authMode"`
	KeyEnv          string `json:"keyEnv,omitempty"`
	ReasoningEffort string `json:"reasoningEffort,omitempty"`
	APIKey          string `json:"apiKey,omitempty"`
}

type ProfileInput struct {
	Name            string  `json:"name"`
	BaseURL         string  `json:"baseUrl"`
	Model           string  `json:"model"`
	Protocol        string  `json:"protocol"`
	AuthMode        string  `json:"authMode"`
	KeyEnv          string  `json:"keyEnv"`
	ReasoningEffort string  `json:"reasoningEffort"`
	APIKey          *string `json:"apiKey"`
}

type ProfileSummary struct {
	ID              string `json:"id"`
	Name            string `json:"name"`
	BaseURL         string `json:"baseUrl"`
	Model           string `json:"model"`
	Protocol        string `json:"protocol"`
	AuthMode        string `json:"authMode"`
	KeyEnv          string `json:"keyEnv,omitempty"`
	ReasoningEffort string `json:"reasoningEffort,omitempty"`
	HasKey          bool   `json:"hasKey"`
	Applied         bool   `json:"applied"`
}

type CurrentModel struct {
	Provider string `json:"provider,omitempty"`
	Model    string `json:"model,omitempty"`
}

type View struct {
	Profiles      []ProfileSummary `json:"profiles"`
	Current       CurrentModel     `json:"current"`
	Revision      string           `json:"revision"`
	ActiveID      string           `json:"activeId,omitempty"`
	Changed       bool             `json:"changed"`
	CanRestore    bool             `json:"canRestore"`
	ConfigPaths   []string         `json:"configPaths"`
	OpenCodeMajor int              `json:"opencodeMajor,omitempty"`
}

type field struct {
	Document string          `json:"document"`
	Path     []string        `json:"path"`
	Value    json.RawMessage `json:"value,omitempty"`
}

type kindState struct {
	Profiles      []Profile `json:"profiles"`
	Original      []field   `json:"original,omitempty"`
	ActiveID      string    `json:"activeId,omitempty"`
	AppliedFields []field   `json:"appliedFields,omitempty"`
	ProfileDigest string    `json:"profileDigest,omitempty"`
	NativeDigest  string    `json:"nativeDigest,omitempty"`
	Paths         []string  `json:"paths,omitempty"`
}

type catalog struct {
	Kinds         map[string]*kindState `json:"kinds"`
	LastOperation string                `json:"lastOperation,omitempty"`
}

var validID = regexp.MustCompile(`^[a-f0-9]{32}$`)
var validEnvironment = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]{0,127}$`)

func newID() (string, error) {
	var data [16]byte
	if _, err := rand.Read(data[:]); err != nil {
		return "", err
	}
	return hex.EncodeToString(data[:]), nil
}

func validateKind(kind string) error {
	if agent.Get(kind) == nil || agent.Get(kind).Kind() != kind {
		return fmt.Errorf("INVALID_AGENT_KIND")
	}
	return nil
}

func profileFromInput(kind, id string, input ProfileInput, previous *Profile) (Profile, error) {
	p := Profile{ID: id, Name: strings.TrimSpace(input.Name), BaseURL: strings.TrimSpace(input.BaseURL), Model: strings.TrimSpace(input.Model),
		Protocol: input.Protocol, AuthMode: input.AuthMode, KeyEnv: strings.TrimSpace(input.KeyEnv), ReasoningEffort: input.ReasoningEffort}
	if previous != nil {
		p.APIKey = previous.APIKey
	}
	if input.APIKey != nil && *input.APIKey != "" {
		p.APIKey = *input.APIKey
	}
	if p.KeyEnv != "" {
		p.APIKey = ""
	}
	u, err := url.Parse(p.BaseURL)
	if p.Name == "" || utf8.RuneCountInString(p.Name) > 64 || len(p.BaseURL) > 2048 || err != nil ||
		(u.Scheme != "http" && u.Scheme != "https") || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" ||
		p.Model == "" || len(p.Model) > 256 || strings.ContainsAny(p.Model+p.Name, "\r\n\x00") || strings.Contains(p.Model+p.Name+p.BaseURL, "{env:") || strings.Contains(p.Model+p.Name+p.BaseURL, "{file:") {
		return Profile{}, fmt.Errorf("INVALID_MODEL_PROFILE")
	}
	p.BaseURL = u.String()
	if p.Protocol != "anthropic-messages" && p.Protocol != "openai-responses" && p.Protocol != "openai-completions" {
		return Profile{}, fmt.Errorf("INVALID_MODEL_PROTOCOL")
	}
	if (kind == "claude" && p.Protocol != "anthropic-messages") || (kind == "codex" && p.Protocol != "openai-responses") {
		return Profile{}, fmt.Errorf("INVALID_MODEL_PROTOCOL")
	}
	if p.AuthMode == "" {
		p.AuthMode = "api_key"
	}
	if p.AuthMode != "api_key" && (kind != "claude" || p.AuthMode != "bearer") {
		return Profile{}, fmt.Errorf("INVALID_MODEL_PROFILE")
	}
	if p.KeyEnv != "" && !validEnvironment.MatchString(p.KeyEnv) {
		return Profile{}, fmt.Errorf("INVALID_MODEL_KEY")
	}
	// Pi and OpenCode interpret some credential strings as commands or file references.
	if (p.KeyEnv == "" && p.APIKey == "") || len(p.APIKey) > 8192 || strings.ContainsAny(p.APIKey, "\r\n\x00") ||
		strings.HasPrefix(p.APIKey, "!") || strings.Contains(p.APIKey, "$") || strings.Contains(p.APIKey, "{env:") || strings.Contains(p.APIKey, "{file:") {
		return Profile{}, fmt.Errorf("INVALID_MODEL_KEY")
	}
	if p.ReasoningEffort != "" && (kind != "codex" || !strings.Contains("|low|medium|high|xhigh|", "|"+p.ReasoningEffort+"|")) {
		return Profile{}, fmt.Errorf("INVALID_MODEL_PROFILE")
	}
	return p, nil
}

func providerID(p Profile) string { return "roami_" + p.ID }

func jsonValue(value any) json.RawMessage {
	data, _ := json.Marshal(value)
	return data
}
