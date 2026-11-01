package agentproviders

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"strings"
)

// LocalSource stays inside Go. HTTP callers must explicitly redact Profile.APIKey.
type LocalSource struct {
	ID, Revision, Kind string
	Profile            Profile
	Unavailable        bool
}

func localSourceID(kind, location string) string {
	digest := sha256.Sum256([]byte(kind + ":" + location))
	return hex.EncodeToString(digest[:16])
}
func sourceSecret(value string) (string, bool) {
	env := ""
	if strings.HasPrefix(value, "{env:") && strings.HasSuffix(value, "}") {
		env = strings.TrimSuffix(strings.TrimPrefix(value, "{env:"), "}")
	}
	if strings.HasPrefix(value, "${") && strings.HasSuffix(value, "}") {
		env = strings.TrimSuffix(strings.TrimPrefix(value, "${"), "}")
	}
	if env != "" {
		if !validEnvironment.MatchString(env) {
			return "", false
		}
		value = os.Getenv(env)
	}
	if value == "" || len(value) > 8192 || strings.ContainsAny(value, "\r\n\x00") || strings.Contains(value, "{file:") || strings.Contains(value, "{env:") || strings.Contains(value, "${") || strings.Contains(value, "$(") || strings.HasPrefix(value, "!") {
		return "", false
	}
	return value, true
}

func (s *Store) LocalSources(ctx context.Context, kind string) ([]LocalSource, error) {
	if err := validateKind(kind); err != nil {
		return nil, err
	}
	result := []LocalSource{}
	err := s.locked(func(state *catalog) error {
		config, err := readNative(ctx, kind, false)
		if err != nil {
			return err
		}
		revision := config.revision()
		add := func(location string, p Profile, supported bool) {
			if p.BaseURL == "" {
				return
			}
			if p.KeyEnv != "" {
				p.APIKey = "{env:" + p.KeyEnv + "}"
			}
			key, ok := sourceSecret(p.APIKey)
			p.APIKey, p.KeyEnv = key, ""
			if p.Name == "" {
				p.Name = kind
			}
			result = append(result, LocalSource{ID: localSourceID(kind, location), Revision: revision, Kind: kind, Profile: p, Unavailable: !supported || !ok})
		}
		for _, profile := range stateFor(state, kind).Profiles {
			add("preset:"+profile.ID, profile, true)
		}
		for _, doc := range config.Documents {
			values, err := doc.values()
			if err != nil {
				return err
			}
			switch kind {
			case "claude":
				key, auth := textAt(values, "env", "ANTHROPIC_API_KEY"), "api_key"
				if token := textAt(values, "env", "ANTHROPIC_AUTH_TOKEN"); token != "" {
					key, auth = token, "bearer"
				}
				current := config.current(kind)
				add("native", Profile{Name: "Claude Code", BaseURL: current.BaseURL, Model: current.Model, Protocol: "anthropic-messages", AuthMode: auth, APIKey: key}, textAt(values, "apiKeyHelper") == "")
			case "codex":
				providers, _ := values["model_providers"].(map[string]any)
				for id := range providers {
					base := textAt(values, "model_providers", id, "base_url")
					key := textAt(values, "model_providers", id, "experimental_bearer_token")
					env := textAt(values, "model_providers", id, "env_key")
					wire := textAt(values, "model_providers", id, "wire_api")
					add("native:"+id, Profile{Name: id, BaseURL: base, Model: textAt(values, "model"), APIKey: key, KeyEnv: env, Protocol: "openai-responses", AuthMode: "bearer"}, wire == "" || wire == "responses")
				}
			case "opencode":
				for _, group := range []string{"provider", "providers"} {
					providers, _ := values[group].(map[string]any)
					options, pack := "options", "npm"
					if group == "providers" {
						options, pack = "settings", "package"
					}
					for id := range providers {
						pkg := textAt(values, group, id, pack)
						protocol := "openai-completions"
						supported := strings.Contains(pkg, "openai") || strings.Contains(pkg, "anthropic")
						if strings.Contains(pkg, "anthropic") {
							protocol = "anthropic-messages"
						} else if strings.HasSuffix(pkg, "/responses") || pkg == "@ai-sdk/openai" {
							protocol = "openai-responses"
						}
						model := ""
						if current := config.current(kind); current.Provider == id {
							model = current.Model
						}
						add("native:"+group+":"+id, Profile{Name: id, BaseURL: textAt(values, group, id, options, "baseURL"), APIKey: textAt(values, group, id, options, "apiKey"), Model: model, Protocol: protocol, AuthMode: "bearer"}, supported)
					}
				}
			case "pi":
				if doc.Name != "models" {
					continue
				}
				providers, _ := values["providers"].(map[string]any)
				for id := range providers {
					protocol := textAt(values, "providers", id, "api")
					supported := containsProtocol(protocol)
					current := config.current(kind)
					model := ""
					if current.Provider == id {
						model = current.Model
					}
					add("native:"+id, Profile{Name: id, BaseURL: textAt(values, "providers", id, "baseUrl"), APIKey: textAt(values, "providers", id, "apiKey"), Model: model, Protocol: protocol, AuthMode: "bearer"}, supported)
				}
			}
		}
		if len(result) > 128 {
			return fmt.Errorf("MODEL_PROFILE_LIMIT")
		}
		return nil
	})
	return result, err
}
func containsProtocol(value string) bool {
	return value == "openai-completions" || value == "openai-responses" || value == "anthropic-messages"
}
