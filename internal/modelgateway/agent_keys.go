package modelgateway

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"github.com/ybz21/Roami/internal/agent"
	"net/http"
	"sort"
	"strings"
	"time"
)

var gatewayAgentKinds = func() []string {
	kinds := agent.Kinds()
	sort.SliceStable(kinds, func(i, j int) bool { return kinds[i] == "opencode" && kinds[j] != "opencode" })
	return append(kinds, "roami")
}()

type agentKeyState struct {
	Pending       bool   `json:"pending,omitempty"`
	ID            string `json:"id"`
	Disabled      bool   `json:"disabled,omitempty"`
	Previous      string `json:"previous,omitempty"`
	PreviousUntil int64  `json:"previousUntil,omitempty"`
	Updated       int64  `json:"updatedMs"`
}

type catalogKeyStatus struct {
	Pending  bool   `json:"pending"`
	Suffix   string `json:"suffix"`
	Disabled bool   `json:"disabled"`
}

type agentKeyView struct {
	Pending        bool   `json:"pending"`
	Kind           string `json:"agentKind"`
	ID             string `json:"keyId"`
	Suffix         string `json:"suffix"`
	Disabled       bool   `json:"disabled"`
	Connected      bool   `json:"connected"`
	ConfigRevision string `json:"configRevision"`
	ConfigChanged  bool   `json:"configChanged"`
	Unavailable    bool   `json:"unavailable"`
	Updated        int64  `json:"updatedMs"`
}

// Keep legacy credentials until that agent is rotated. Only generation IDs are persisted.
func (s *CatalogStore) deriveCredential(kind, generation string) string {
	mac := hmac.New(sha256.New, []byte(s.value.Token))
	_, _ = mac.Write([]byte(kind))
	if generation != "" {
		_, _ = mac.Write([]byte(":" + generation))
	}
	return hex.EncodeToString(mac.Sum(nil))
}
func (s *CatalogStore) credential(kind string) string {
	return s.deriveCredential(kind, s.value.AgentKeys[kind].ID)
}
func (s *CatalogStore) keyAllowed(kind, id string) bool {
	state := s.value.AgentKeys[kind]
	return !state.Disabled && (id == keyID(state.ID) || id == keyID(state.Previous) && state.PreviousUntil > s.ledger.now().UnixMilli())
}
func keyID(id string) string {
	if id == "" {
		return "legacy"
	}
	return id
}
func (s *CatalogStore) authenticate(key string) (string, string) {
	for _, kind := range gatewayAgentKinds {
		state := s.value.AgentKeys[kind]
		if state.Disabled {
			continue
		}
		if subtle.ConstantTimeCompare([]byte(key), []byte(s.credential(kind))) == 1 {
			return kind, keyID(state.ID)
		}
		if state.PreviousUntil > s.ledger.now().UnixMilli() && subtle.ConstantTimeCompare([]byte(key), []byte(s.deriveCredential(kind, state.Previous))) == 1 {
			return kind, keyID(state.Previous)
		}
	}
	return "", ""
}
func gatewayEndpoint(base, endpoint string) bool { return endpoint == base || endpoint == base+"/v1" }
func (s *CatalogStore) keyView(ctx context.Context, kind string) agentKeyView {
	state := s.value.AgentKeys[kind]
	key := s.credential(kind)
	row := agentKeyView{Pending: state.Pending, Kind: kind, ID: keyID(state.ID), Suffix: key[len(key)-8:], Disabled: state.Disabled, Updated: state.Updated}
	if kind == "roami" {
		main, e1 := readNodeModels(s.ledger.paths, "main")
		worker, e2 := readNodeModels(s.ledger.paths, "worker")
		row.Unavailable = e1 != nil || e2 != nil
		row.Connected = gatewayEndpoint(s.baseURL, main.endpoint) || gatewayEndpoint(s.baseURL, worker.endpoint)
	} else {
		view, err := s.agents.View(ctx, kind)
		row.Unavailable = err != nil
		row.ConfigRevision, row.ConfigChanged = view.Revision, view.Changed
		row.Connected = gatewayEndpoint(s.baseURL, view.Current.BaseURL)
	}
	return row
}
func (s *CatalogStore) keysView(ctx context.Context) map[string]any {
	rows := []agentKeyView{}
	for _, kind := range gatewayAgentKinds {
		rows = append(rows, s.keyView(ctx, kind))
	}
	return map[string]any{"revision": s.value.Revision, "keys": rows}
}

func (h *Handler) agentKeysManagement(w http.ResponseWriter, r *http.Request) bool {
	const path = "/v1/model-gateway/keys"
	if r.URL.Path != path && !strings.HasPrefix(r.URL.Path, path+"/") {
		return false
	}
	if h.Catalog == nil {
		reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return true
	}
	s := h.Catalog
	s.mu.Lock()
	defer func() {
		s.mu.Unlock()
		if r.Method == "POST" {
			h.notifyAdmission()
		}
	}()
	if r.URL.Path == path && r.Method == "GET" {
		writeJSON(w, 200, map[string]any{"data": s.keysView(r.Context())})
		return true
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, path+"/"), "/")
	if len(parts) != 2 || !containsField(gatewayAgentKinds, parts[0]) || !containsField([]string{"rotate", "disable"}, parts[1]) || r.Method != "POST" {
		reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	var input struct {
		Revision       string `json:"revision"`
		ConfigRevision string `json:"configRevision"`
	}
	if decodeBody(w, r, &input) != nil {
		reject(w, 400, "INVALID_MODEL_CATALOG")
		return true
	}
	if s.applying || input.Revision != s.value.Revision {
		reject(w, 409, "MODEL_CATALOG_CHANGED")
		return true
	}
	kind, action := parts[0], parts[1]
	next := s.snapshot()
	state := next.AgentKeys[kind]
	if action == "disable" {
		state.Disabled, state.Pending, state.PreviousUntil, state.Updated = true, false, 0, s.ledger.now().UnixMilli()
		next.AgentKeys[kind] = state
		if s.persist(next) != nil {
			reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			return true
		}
		writeJSON(w, 200, map[string]any{"data": s.keysView(r.Context())})
		return true
	}
	current := s.keyView(r.Context(), kind)
	if current.Unavailable || current.ConfigChanged || kind != "roami" && current.ConfigRevision != input.ConfigRevision {
		reject(w, 409, "AGENT_CONFIG_CHANGED")
		return true
	}
	id, err := randomCatalogID()
	if state.Pending {
		id = state.ID
	}
	if err != nil {
		reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		return true
	}
	// Persist the overlap before writing native config so a crash cannot strand either credential.
	next.AgentKeys[kind] = agentKeyState{ID: id, Previous: state.ID, PreviousUntil: int64(1<<63 - 1), Pending: true, Updated: s.ledger.now().UnixMilli()}
	if state.Pending {
		next.AgentKeys[kind] = state
	}
	if state.Disabled {
		rotated := next.AgentKeys[kind]
		rotated.PreviousUntil = 0
		next.AgentKeys[kind] = rotated
	}
	if s.persist(next) != nil {
		reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		return true
	}
	key := s.credential(kind)
	if current.Connected {
		if kind == "roami" {
			s.applying = true
			s.mu.Unlock()
			_, err = s.runtimeModels(r, "PUT", map[string]any{"connection": map[string]any{"baseUrl": s.baseURL + "/v1", "apiKey": key}})
			s.mu.Lock()
			s.applying = false
		} else {
			err = s.agents.ReplaceGatewayKey(r.Context(), kind, s.baseURL, key, input.ConfigRevision)
		}
	}
	if err != nil {
		// Native writes use the provider journal; keep both keys only if recovery needs intervention.
		if !errors.Is(err, context.Canceled) && err.Error() != "AGENT_CONFIG_RECOVERY_REQUIRED" {
			rollback := s.snapshot()
			rollback.AgentKeys[kind] = state
			if s.persist(rollback) != nil {
				reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
				return true
			}
		}
		reject(w, 409, err.Error())
		return true
	}
	committed := s.snapshot()
	active := committed.AgentKeys[kind]
	active.Pending = false
	if active.PreviousUntil != 0 {
		active.PreviousUntil = s.ledger.now().Add(5 * time.Minute).UnixMilli()
	}
	committed.AgentKeys[kind] = active
	if s.persist(committed) != nil {
		reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		return true
	}
	writeJSON(w, 200, map[string]any{"data": s.keysView(r.Context()), "key": key})
	return true
}
