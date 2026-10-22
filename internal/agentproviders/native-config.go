package agentproviders

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/ybz21/Roami/internal/agentinventory"
)

const maxFileSize = 1 << 20

type document struct {
	Name   string `json:"name"`
	Path   string `json:"path"`
	Data   []byte `json:"data"`
	Exists bool   `json:"exists"`
	IsTOML bool   `json:"isToml"`
}

type nativeConfig struct {
	Documents []document
	Major     int
}

func configDirectory(environment string, fallback string) (string, error) {
	path := os.Getenv(environment)
	if path == "" {
		path = fallback
	}
	if !filepath.IsAbs(path) {
		return "", fmt.Errorf("AGENT_CONFIG_PATH_INVALID")
	}
	return filepath.Clean(path), nil
}

func loadNative(ctx context.Context, kind string) (nativeConfig, error) {
	return readNative(ctx, kind, true)
}

func readNative(ctx context.Context, kind string, checkVersion bool) (nativeConfig, error) {
	home, err := os.UserHomeDir()
	if err != nil || !filepath.IsAbs(home) {
		return nativeConfig{}, fmt.Errorf("AGENT_CONFIG_PATH_INVALID")
	}
	var docs []document
	var dir string
	major := 0
	switch kind {
	case "claude":
		dir, err = configDirectory("CLAUDE_CONFIG_DIR", filepath.Join(home, ".claude"))
		docs = []document{{Name: "settings", Path: filepath.Join(dir, "settings.json")}}
	case "codex":
		dir, err = configDirectory("CODEX_HOME", filepath.Join(home, ".codex"))
		docs = []document{{Name: "config", Path: filepath.Join(dir, "config.toml"), IsTOML: true}}
	case "pi":
		dir, err = configDirectory("PI_CODING_AGENT_DIR", filepath.Join(home, ".pi", "agent"))
		docs = []document{{Name: "settings", Path: filepath.Join(dir, "settings.json")}, {Name: "models", Path: filepath.Join(dir, "models.json")}}
	case "opencode":
		dir, err = configDirectory("XDG_CONFIG_HOME", filepath.Join(home, ".config"))
		path := os.Getenv("OPENCODE_CONFIG")
		if path == "" {
			path = filepath.Join(dir, "opencode", "opencode.json")
			if _, statErr := os.Stat(path + "c"); statErr == nil {
				path += "c"
			}
		}
		if os.Getenv("OPENCODE_CONFIG_CONTENT") != "" {
			return nativeConfig{}, fmt.Errorf("AGENT_CONFIG_INLINE_OVERRIDE")
		}
		docs = []document{{Name: "config", Path: path}}
		var row agentinventory.ProfessionalAgent
		var checkErr error
		if checkVersion {
			row, checkErr = agentinventory.CheckProfessionalAgent(ctx, kind)
		}
		if checkErr == nil && checkVersion {
			match := regexp.MustCompile(`(?:^|\s)v?([0-9]+)\.`).FindStringSubmatch(row.Version)
			if len(match) == 2 {
				if match[1] == "1" {
					major = 1
				} else if match[1] == "2" {
					major = 2
				}
			}
		}
	}
	if err != nil {
		return nativeConfig{}, err
	}
	for i := range docs {
		docs[i], err = readDocument(docs[i])
		if err != nil {
			return nativeConfig{}, err
		}
		if _, err := docs[i].values(); err != nil {
			return nativeConfig{}, err
		}
	}
	return nativeConfig{Documents: docs, Major: major}, nil
}

func readDocument(doc document) (document, error) {
	if !filepath.IsAbs(doc.Path) {
		return document{}, fmt.Errorf("AGENT_CONFIG_PATH_INVALID")
	}
	resolved, err := filepath.EvalSymlinks(doc.Path)
	if err == nil {
		doc.Path = resolved
	} else if !os.IsNotExist(err) {
		return document{}, fmt.Errorf("AGENT_CONFIG_READ_FAILED")
	} else if info, linkErr := os.Lstat(doc.Path); linkErr == nil && info.Mode()&os.ModeSymlink != 0 {
		return document{}, fmt.Errorf("AGENT_CONFIG_PATH_INVALID")
	}
	f, err := os.Open(doc.Path)
	if os.IsNotExist(err) {
		doc.Exists, doc.Data = false, nil
		return doc, nil
	}
	if err != nil {
		return document{}, fmt.Errorf("AGENT_CONFIG_READ_FAILED")
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Size() > maxFileSize {
		return document{}, fmt.Errorf("AGENT_CONFIG_INVALID")
	}
	doc.Data, err = io.ReadAll(io.LimitReader(f, maxFileSize+1))
	if err != nil || len(doc.Data) > maxFileSize {
		return document{}, fmt.Errorf("AGENT_CONFIG_READ_FAILED")
	}
	doc.Exists = true
	return doc, nil
}

func (doc document) values() (map[string]any, error) {
	if doc.IsTOML {
		return tomlDocument(doc.Data)
	}
	return jsonDocument(doc.Data)
}

func valueAt(value map[string]any, path []string) json.RawMessage {
	var current any = value
	for _, key := range path {
		object, ok := current.(map[string]any)
		if !ok {
			return nil
		}
		current, ok = object[key]
		if !ok {
			return nil
		}
	}
	return jsonValue(current)
}

func textAt(value map[string]any, path ...string) string {
	var text string
	_ = json.Unmarshal(valueAt(value, path), &text)
	return text
}

func digest(value any) string {
	hash := sha256.Sum256(jsonValue(value))
	return hex.EncodeToString(hash[:])
}

func (config nativeConfig) revision() string { return digest(config.Documents) }

func (config nativeConfig) capture(fields []field) ([]field, error) {
	result := make([]field, len(fields))
	for i, item := range fields {
		result[i] = field{Document: item.Document, Path: item.Path}
		for _, doc := range config.Documents {
			if doc.Name == item.Document {
				values, err := doc.values()
				if err != nil {
					return nil, err
				}
				result[i].Value = valueAt(values, item.Path)
			}
		}
	}
	return result, nil
}

func defaultFields(kind string) []field {
	paths := [][]string{}
	doc := "config"
	switch kind {
	case "claude":
		doc = "settings"
		paths = [][]string{{"model"}}
		for _, name := range []string{"ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_MODEL"} {
			paths = append(paths, []string{"env", name})
		}
	case "codex":
		paths = [][]string{{"model_provider"}, {"model"}, {"model_reasoning_effort"}}
	case "opencode":
		paths = [][]string{{"model"}}
	case "pi":
		doc = "settings"
		paths = [][]string{{"defaultProvider"}, {"defaultModel"}}
	}
	result := make([]field, 0, len(paths))
	for _, path := range paths {
		result = append(result, field{Document: doc, Path: path})
	}
	return result
}

func (config nativeConfig) current(kind string) CurrentModel {
	for _, doc := range config.Documents {
		values, _ := doc.values()
		switch kind {
		case "claude":
			model := textAt(values, "env", "ANTHROPIC_MODEL")
			if model == "" {
				model = textAt(values, "model")
			}
			return CurrentModel{Model: model}
		case "codex":
			return CurrentModel{Provider: textAt(values, "model_provider"), Model: textAt(values, "model")}
		case "opencode":
			ref := textAt(values, "model")
			provider, model, found := strings.Cut(ref, "/")
			if !found {
				return CurrentModel{Model: ref}
			}
			return CurrentModel{Provider: provider, Model: model}
		case "pi":
			if doc.Name == "settings" {
				return CurrentModel{Provider: textAt(values, "defaultProvider"), Model: textAt(values, "defaultModel")}
			}
		}
	}
	return CurrentModel{}
}

func (config nativeConfig) render(fields []field) (nativeConfig, error) {
	result := nativeConfig{Major: config.Major, Documents: append([]document{}, config.Documents...)}
	for _, item := range fields {
		for i := range result.Documents {
			doc := &result.Documents[i]
			if doc.Name != item.Document {
				continue
			}
			var err error
			if doc.IsTOML {
				doc.Data, err = patchTOML(doc.Data, item.Path, item.Value)
			} else {
				doc.Data, err = patchJSON(doc.Data, item.Path, item.Value)
			}
			if err != nil {
				return nativeConfig{}, err
			}
			if len(doc.Data) > maxFileSize {
				return nativeConfig{}, fmt.Errorf("AGENT_CONFIG_TOO_LARGE")
			}
			doc.Exists = true
		}
	}
	return result, nil
}

func profileFields(kind string, profile Profile, major int) ([]field, error) {
	key := profile.APIKey
	if profile.KeyEnv != "" {
		switch kind {
		case "claude":
			key = os.Getenv(profile.KeyEnv)
			if key == "" || strings.ContainsAny(key, "\r\n\x00") {
				return nil, fmt.Errorf("MODEL_KEY_ENV_MISSING")
			}
		case "opencode":
			key = "{env:" + profile.KeyEnv + "}"
		case "pi":
			key = "${" + profile.KeyEnv + "}"
		}
	}
	fields := []field{}
	add := func(doc string, value any, path ...string) {
		var raw json.RawMessage
		if value != nil {
			raw = jsonValue(value)
		}
		fields = append(fields, field{Document: doc, Path: path, Value: raw})
	}
	provider := providerID(profile)
	switch kind {
	case "claude":
		add("settings", profile.Model, "model")
		add("settings", profile.Model, "env", "ANTHROPIC_MODEL")
		add("settings", profile.BaseURL, "env", "ANTHROPIC_BASE_URL")
		keyName, clearName := "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"
		if profile.AuthMode == "bearer" {
			keyName, clearName = clearName, keyName
		}
		add("settings", key, "env", keyName)
		add("settings", nil, "env", clearName)
	case "codex":
		add("config", provider, "model_provider")
		add("config", profile.Model, "model")
		var effort any
		if profile.ReasoningEffort != "" {
			effort = profile.ReasoningEffort
		}
		add("config", effort, "model_reasoning_effort")
		for _, item := range [][2]string{{"name", profile.Name}, {"base_url", profile.BaseURL}, {"wire_api", "responses"}} {
			add("config", item[1], "model_providers", provider, item[0])
		}
		if profile.KeyEnv != "" {
			add("config", profile.KeyEnv, "model_providers", provider, "env_key")
			add("config", nil, "model_providers", provider, "experimental_bearer_token")
		} else {
			add("config", key, "model_providers", provider, "experimental_bearer_token")
			add("config", nil, "model_providers", provider, "env_key")
		}
	case "opencode":
		if major != 1 && major != 2 {
			return nil, fmt.Errorf("OPENCODE_CONFIG_VERSION_UNKNOWN")
		}
		add("config", provider+"/"+profile.Model, "model")
		models := map[string]any{profile.Model: map[string]any{"name": profile.Model}}
		settings := map[string]any{"baseURL": profile.BaseURL, "apiKey": key}
		packages := map[string]string{"openai-responses": "@opencode/ai/providers/openai-compatible/responses", "openai-completions": "@opencode/ai/providers/openai-compatible", "anthropic-messages": "@opencode/ai/providers/anthropic-compatible"}
		if major == 2 {
			add("config", map[string]any{"name": profile.Name, "package": packages[profile.Protocol], "settings": settings, "models": models}, "providers", provider)
		} else {
			packages = map[string]string{"openai-responses": "@ai-sdk/openai", "openai-completions": "@ai-sdk/openai-compatible", "anthropic-messages": "@ai-sdk/anthropic"}
			add("config", map[string]any{"name": profile.Name, "npm": packages[profile.Protocol], "options": settings, "models": models}, "provider", provider)
		}
	case "pi":
		add("settings", provider, "defaultProvider")
		add("settings", profile.Model, "defaultModel")
		add("models", map[string]any{"name": profile.Name, "baseUrl": profile.BaseURL, "apiKey": key, "api": profile.Protocol, "models": []any{map[string]any{"id": profile.Model, "name": profile.Model}}}, "providers", provider)
	}
	return fields, nil
}

func writePrivate(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".roami-provider-*")
	if err != nil {
		return err
	}
	temp := f.Name()
	defer os.Remove(temp)
	if _, err = f.Write(data); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err := os.Rename(temp, path); err != nil {
		return err
	}
	if dir, err := os.Open(filepath.Dir(path)); err == nil {
		_ = dir.Sync()
		_ = dir.Close()
	}
	return nil
}

func configPaths(config nativeConfig) []string {
	paths := []string{}
	for _, doc := range config.Documents {
		paths = append(paths, doc.Path)
	}
	sort.Strings(paths)
	return paths
}
