package hostroute

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"unicode"

	"github.com/pelletier/go-toml/v2"
	"github.com/ybz21/Roami/internal/fsguard"
	metadb "github.com/ybz21/Roami/internal/storage"
)

var generationKeys = []string{"temperature", "top_p", "max_tokens", "reasoning_effort"}

type Route struct {
	Endpoint, Model, Key string
	Parameters           map[string]any
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

func Read(paths metadb.Paths, role string) (Route, error) {
	if paths.Home == "" || paths.Data == "" {
		return Route{}, invalidNodeRoute()
	}
	if role == "memory" {
		role = "worker"
	}
	if role != "main" && role != "worker" {
		return Route{}, errors.New("INVALID_MODEL_CONFIG")
	}
	var config nodeModelConfiguration
	raw, err := os.ReadFile(filepath.Join(paths.Home, "agent.toml"))
	if err != nil && !os.IsNotExist(err) {
		return Route{}, invalidNodeRoute()
	}
	if len(raw) > 1<<20 || len(raw) > 0 && toml.Unmarshal(raw, &config) != nil {
		return Route{}, invalidNodeRoute()
	}
	keyEnv := config.Model.KeyEnv
	if keyEnv == "" {
		keyEnv = "ROAMI_AGENT_API_KEY"
	}
	mainKeyEnv := keyEnv
	route := Route{Endpoint: config.Model.Endpoint, Model: config.Model.Name, Parameters: config.Model.Parameters}
	if role == "worker" {
		if config.Model.Worker != "" {
			route.Model = config.Model.Worker
		}
		if worker := config.Worker.Model; worker != nil {
			if worker.Endpoint != nil {
				route.Endpoint = *worker.Endpoint
			}
			if worker.Name != nil {
				route.Model = *worker.Name
			}
			if worker.KeyEnv != nil {
				keyEnv = *worker.KeyEnv
			}
			route.Parameters = worker.Parameters
		}
	}
	saved, err := readSavedNodeModels(filepath.Join(paths.Data, "agents", "model-settings.json"))
	if err != nil {
		return Route{}, err
	}
	row := map[string]any{}
	if rawRow, ok := saved[role]; ok {
		var valid bool
		row, valid = rawRow.(map[string]any)
		if !valid {
			return Route{}, invalidNodeRoute()
		}
	}
	for key := range row {
		if !slices.Contains([]string{"baseUrl", "model", "apiKey", "images", "contextWindow", "reasoningEffort"}, key) {
			return Route{}, invalidNodeRoute()
		}
	}
	var secret string
	if connection, exists := saved["connection"]; exists && connection != nil {
		values, ok := connection.(map[string]any)
		if !ok {
			return Route{}, invalidNodeRoute()
		}
		for key, value := range values {
			if !slices.Contains([]string{"baseUrl", "apiKey"}, key) {
				return Route{}, invalidNodeRoute()
			}
			if _, ok := value.(string); !ok {
				return Route{}, invalidNodeRoute()
			}
		}
		route.Endpoint, err = routeString(values, "baseUrl", config.Model.Endpoint)
		if err != nil {
			return Route{}, err
		}
		secret, err = routeString(values, "apiKey", "")
		keyEnv = mainKeyEnv
	} else {
		route.Endpoint, err = routeString(row, "baseUrl", route.Endpoint)
		if err != nil {
			return Route{}, err
		}
		secret, err = routeString(row, "apiKey", "")
	}
	if err != nil {
		return Route{}, err
	}
	route.Model, err = routeString(row, "model", route.Model)
	if err != nil {
		return Route{}, err
	}
	route.Endpoint = strings.TrimRight(strings.TrimSpace(route.Endpoint), "/")
	route.Model = strings.TrimSpace(route.Model)
	if route.Endpoint == "" || route.Model == "" {
		return Route{}, errors.New("MODEL_NOT_CONFIGURED")
	}
	target, err := url.Parse(route.Endpoint)
	if err != nil || target.Host == "" || target.User != nil || target.RawQuery != "" || target.Fragment != "" || len(route.Model) > 200 || strings.IndexFunc(route.Endpoint, unicode.IsSpace) >= 0 {
		return Route{}, invalidNodeRoute()
	}
	if target.Port() != "" {
		port, err := strconv.Atoi(target.Port())
		if err != nil || port < 1 || port > 65535 {
			return Route{}, invalidNodeRoute()
		}
	}
	if !allowedNodeModelURL(target) {
		return Route{}, invalidNodeRoute()
	}
	if secret == "" {
		secret = os.Getenv(keyEnv)
	}
	if strings.ContainsAny(secret, "\r\n") {
		return Route{}, invalidNodeRoute()
	}
	route.Key = secret
	// Normalize TOML integers to the same JSON number representation as incoming requests.
	normalized, err := json.Marshal(route.Parameters)
	if err != nil {
		return Route{}, invalidNodeRoute()
	}
	route.Parameters = map[string]any{}
	if string(normalized) != "null" && json.Unmarshal(normalized, &route.Parameters) != nil {
		return Route{}, invalidNodeRoute()
	}
	if effort, ok := row["reasoningEffort"]; ok {
		delete(route.Parameters, "reasoning_effort")
		if effort != nil {
			text, valid := effort.(string)
			if !valid || !slices.Contains([]string{"none", "minimal", "low", "medium", "high", "xhigh", "max"}, text) {
				return Route{}, invalidNodeRoute()
			}
			route.Parameters["reasoning_effort"] = text
		}
	}
	for key := range route.Parameters {
		if !slices.Contains(generationKeys, key) {
			return Route{}, invalidNodeRoute()
		}
	}
	for key, raw := range route.Parameters {
		switch key {
		case "temperature", "top_p", "max_tokens":
			value, ok := raw.(float64)
			if !ok || math.IsNaN(value) || math.IsInf(value, 0) {
				return Route{}, invalidNodeRoute()
			}
			if key == "temperature" && (value < 0 || value > 2) || key == "top_p" && (value < 0 || value > 1) || key == "max_tokens" && (value < 1 || value > 1000000 || value != math.Trunc(value)) {
				return Route{}, invalidNodeRoute()
			}
		case "reasoning_effort":
			text, ok := raw.(string)
			if !ok || !slices.Contains([]string{"none", "minimal", "low", "medium", "high", "xhigh", "max"}, text) {
				return Route{}, invalidNodeRoute()
			}
		}
	}
	return route, nil
}

func allowedNodeModelURL(u *url.URL) bool {
	ip := net.ParseIP(u.Hostname())
	return u.Scheme == "https" || u.Scheme == "http" && (u.Hostname() == "localhost" || ip != nil && (ip.IsLoopback() || ip.IsPrivate()))
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

func readSavedNodeModels(path string) (map[string]any, error) {
	info, err := os.Lstat(path)
	if os.IsNotExist(err) {
		return map[string]any{}, nil
	}
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || info.Size() > 32000 {
		return nil, invalidNodeRoute()
	}
	if !fsguard.OwnedByCurrentUser(info) {
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
		if !slices.Contains([]string{"main", "worker", "connection", "proxy"}, key) {
			return nil, invalidNodeRoute()
		}
	}
	return value, nil
}

func (route Route) Identity() string {
	sum := sha256.Sum256([]byte(route.Endpoint + "\x00" + route.Model))
	return hex.EncodeToString(sum[:])
}

func (route Route) Accepts(body map[string]any, identity string) bool {
	if body["model"] != route.Model || identity != "" && identity != route.Identity() {
		return false
	}
	for _, key := range generationKeys {
		requested, exists := body[key]
		configured, present := route.Parameters[key]
		if exists != present || !reflect.DeepEqual(requested, configured) {
			return false
		}
	}
	return true
}
