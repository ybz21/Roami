package modelgateway

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"syscall"
	"unicode"

	"github.com/pelletier/go-toml/v2"
	metadb "github.com/ybz21/Roami/internal/storage"
)

var generationKeys = []string{"temperature", "top_p", "max_tokens", "reasoning_effort"}

type nodeModelRoute struct {
	endpoint, model, key string
	parameters           map[string]any
}

type storedModelRoute struct {
	Endpoint   *string        `toml:"endpoint"`
	Name       *string        `toml:"name"`
	KeyEnv     *string        `toml:"key_env"`
	Parameters map[string]any `toml:"parameters"`
}

type nodeModelConfiguration struct {
	Model struct {
		Endpoint   string         `toml:"endpoint"`
		Name       string         `toml:"name"`
		KeyEnv     string         `toml:"key_env"`
		Worker     string         `toml:"worker"`
		Parameters map[string]any `toml:"parameters"`
	} `toml:"model"`
	Worker struct {
		Model *storedModelRoute `toml:"model"`
	} `toml:"worker"`
}

func invalidNodeRoute() error { return errors.New("MODEL_GATEWAY_CONFIGURATION_INVALID") }

func readNodeModels(paths metadb.Paths, role string) (nodeModelRoute, error) {
	if paths.Home == "" || paths.Data == "" {
		return nodeModelRoute{}, invalidNodeRoute()
	}
	if role == "memory" {
		role = "worker"
	}
	if role != "main" && role != "worker" {
		return nodeModelRoute{}, errors.New("INVALID_MODEL_CONFIG")
	}
	var config nodeModelConfiguration
	raw, err := os.ReadFile(filepath.Join(paths.Home, "agent.toml"))
	if err != nil && !os.IsNotExist(err) {
		return nodeModelRoute{}, invalidNodeRoute()
	}
	if len(raw) > 1<<20 || len(raw) > 0 && toml.Unmarshal(raw, &config) != nil {
		return nodeModelRoute{}, invalidNodeRoute()
	}
	keyEnv := config.Model.KeyEnv
	if keyEnv == "" {
		keyEnv = "ROAMI_AGENT_API_KEY"
	}
	mainKeyEnv := keyEnv
	route := nodeModelRoute{endpoint: config.Model.Endpoint, model: config.Model.Name, parameters: config.Model.Parameters}
	if role == "worker" {
		if config.Model.Worker != "" {
			route.model = config.Model.Worker
		}
		if worker := config.Worker.Model; worker != nil {
			if worker.Endpoint != nil {
				route.endpoint = *worker.Endpoint
			}
			if worker.Name != nil {
				route.model = *worker.Name
			}
			if worker.KeyEnv != nil {
				keyEnv = *worker.KeyEnv
			}
			route.parameters = worker.Parameters
		}
	}
	saved, err := readSavedNodeModels(filepath.Join(paths.Data, "agents", "model-settings.json"))
	if err != nil {
		return nodeModelRoute{}, err
	}
	row := map[string]any{}
	if rawRow, ok := saved[role]; ok {
		var valid bool
		row, valid = rawRow.(map[string]any)
		if !valid {
			return nodeModelRoute{}, invalidNodeRoute()
		}
	}
	for key := range row {
		if !containsField([]string{"baseUrl", "model", "apiKey", "images", "contextWindow", "reasoningEffort"}, key) {
			return nodeModelRoute{}, invalidNodeRoute()
		}
	}
	var secret string
	if connection, exists := saved["connection"]; exists && connection != nil {
		values, ok := connection.(map[string]any)
		if !ok {
			return nodeModelRoute{}, invalidNodeRoute()
		}
		for key, value := range values {
			if !containsField([]string{"baseUrl", "apiKey"}, key) {
				return nodeModelRoute{}, invalidNodeRoute()
			}
			if _, ok := value.(string); !ok {
				return nodeModelRoute{}, invalidNodeRoute()
			}
		}
		route.endpoint, err = routeString(values, "baseUrl", config.Model.Endpoint)
		if err != nil {
			return nodeModelRoute{}, err
		}
		secret, err = routeString(values, "apiKey", "")
		keyEnv = mainKeyEnv
	} else {
		route.endpoint, err = routeString(row, "baseUrl", route.endpoint)
		if err != nil {
			return nodeModelRoute{}, err
		}
		secret, err = routeString(row, "apiKey", "")
	}
	if err != nil {
		return nodeModelRoute{}, err
	}
	route.model, err = routeString(row, "model", route.model)
	if err != nil {
		return nodeModelRoute{}, err
	}
	route.endpoint = strings.TrimRight(strings.TrimSpace(route.endpoint), "/")
	route.model = strings.TrimSpace(route.model)
	if route.endpoint == "" || route.model == "" {
		return nodeModelRoute{}, errors.New("MODEL_NOT_CONFIGURED")
	}
	target, err := url.Parse(route.endpoint)
	if err != nil || target.Host == "" || target.User != nil || target.RawQuery != "" || target.Fragment != "" || len(route.model) > 200 || strings.IndexFunc(route.endpoint, unicode.IsSpace) >= 0 {
		return nodeModelRoute{}, invalidNodeRoute()
	}
	if target.Port() != "" {
		port, err := strconv.Atoi(target.Port())
		if err != nil || port < 1 || port > 65535 {
			return nodeModelRoute{}, invalidNodeRoute()
		}
	}
	if target.Scheme != "https" && !(target.Scheme == "http" && containsField([]string{"localhost", "127.0.0.1", "::1"}, target.Hostname())) {
		return nodeModelRoute{}, invalidNodeRoute()
	}
	if secret == "" {
		secret = os.Getenv(keyEnv)
	}
	if strings.ContainsAny(secret, "\r\n") {
		return nodeModelRoute{}, invalidNodeRoute()
	}
	route.key = secret
	// Normalize TOML integers to the same JSON number representation as incoming requests.
	normalized, err := json.Marshal(route.parameters)
	if err != nil {
		return nodeModelRoute{}, invalidNodeRoute()
	}
	route.parameters = map[string]any{}
	if string(normalized) != "null" && json.Unmarshal(normalized, &route.parameters) != nil {
		return nodeModelRoute{}, invalidNodeRoute()
	}
	if effort, ok := row["reasoningEffort"]; ok {
		delete(route.parameters, "reasoning_effort")
		if effort != nil {
			text, valid := effort.(string)
			if !valid || !containsField([]string{"none", "minimal", "low", "medium", "high", "xhigh", "max"}, text) {
				return nodeModelRoute{}, invalidNodeRoute()
			}
			route.parameters["reasoning_effort"] = text
		}
	}
	for key := range route.parameters {
		if !containsField(generationKeys, key) {
			return nodeModelRoute{}, invalidNodeRoute()
		}
	}
	for key, raw := range route.parameters {
		switch key {
		case "temperature", "top_p", "max_tokens":
			value, ok := raw.(float64)
			if !ok || math.IsNaN(value) || math.IsInf(value, 0) {
				return nodeModelRoute{}, invalidNodeRoute()
			}
			if key == "temperature" && (value < 0 || value > 2) || key == "top_p" && (value < 0 || value > 1) || key == "max_tokens" && (value < 1 || value > 1000000 || value != math.Trunc(value)) {
				return nodeModelRoute{}, invalidNodeRoute()
			}
		case "reasoning_effort":
			text, ok := raw.(string)
			if !ok || !containsField([]string{"none", "minimal", "low", "medium", "high", "xhigh", "max"}, text) {
				return nodeModelRoute{}, invalidNodeRoute()
			}
		}
	}
	return route, nil
}

func routeString(values map[string]any, key, fallback string) (string, error) {
	value, ok := values[key]
	if !ok {
		return fallback, nil
	}
	text, ok := value.(string)
	if !ok {
		return "", invalidNodeRoute()
	}
	return text, nil
}

func containsField(fields []string, value string) bool {
	for _, field := range fields {
		if field == value {
			return true
		}
	}
	return false
}

func readSavedNodeModels(path string) (map[string]any, error) {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return map[string]any{}, nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 32000 {
		return nil, invalidNodeRoute()
	}
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(owner.Uid) != os.Geteuid() {
		return nil, invalidNodeRoute()
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, invalidNodeRoute()
	}
	var value map[string]any
	if json.Unmarshal(raw, &value) != nil || value == nil {
		return nil, invalidNodeRoute()
	}
	for key := range value {
		if !containsField([]string{"main", "worker", "connection", "proxy"}, key) {
			return nil, invalidNodeRoute()
		}
	}
	return value, nil
}

func (route nodeModelRoute) identity() string {
	sum := sha256.Sum256([]byte(route.endpoint + "\x00" + route.model))
	return hex.EncodeToString(sum[:])
}

func (route nodeModelRoute) accepts(body map[string]any, identity string) bool {
	if body["model"] != route.model || identity != "" && identity != route.identity() {
		return false
	}
	for _, key := range generationKeys {
		requested, exists := body[key]
		configured, present := route.parameters[key]
		if exists != present || !reflect.DeepEqual(requested, configured) {
			return false
		}
	}
	return true
}
