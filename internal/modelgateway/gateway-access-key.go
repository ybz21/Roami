package modelgateway

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"net/http"
)

type gatewayAccessKey struct {
	Hash    string `json:"hash,omitempty"`
	ID      string `json:"id,omitempty"`
	Suffix  string `json:"suffix,omitempty"`
	Updated int64  `json:"updatedMs,omitempty"`
}

func validGatewayAccessKey(key string) bool {
	if len(key) < 16 || len(key) > 512 {
		return false
	}
	for _, b := range []byte(key) {
		if b < 33 || b > 126 {
			return false
		}
	}
	return true
}

func (s *CatalogStore) reservedAgentCredential(key string) bool {
	if subtle.ConstantTimeCompare([]byte(key), []byte(s.value.Token)) == 1 {
		return true
	}
	for _, kind := range gatewayAgentKinds {
		for _, reserved := range []string{s.credential(kind), s.deriveCredential(kind, ""), s.deriveCredential(kind, s.value.AgentKeys[kind].Previous)} {
			if subtle.ConstantTimeCompare([]byte(key), []byte(reserved)) == 1 {
				return true
			}
		}
	}
	return false
}

func validStoredGatewayAccessKey(key gatewayAccessKey) bool {
	if key.Hash == "" {
		return key.ID == "" && key.Suffix == "" && key.Updated == 0
	}
	hash, e1 := hex.DecodeString(key.Hash)
	id, e2 := hex.DecodeString(key.ID)
	return e1 == nil && len(hash) == 32 && e2 == nil && len(id) == 24 && len(key.Suffix) == 8
}

func (s *CatalogStore) accessKeyView() map[string]any {
	key := s.value.AccessKey
	return map[string]any{"revision": s.value.Revision, "hasKey": key.Hash != "", "suffix": key.Suffix}
}

func (h *Handler) accessKeyManagement(w http.ResponseWriter, r *http.Request) bool {
	if r.URL.Path != "/v1/model-gateway/access-key" {
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
		if r.Method != "GET" {
			h.notifyAdmission()
		}
	}()
	if r.Method == "GET" {
		writeJSON(w, 200, map[string]any{"data": s.accessKeyView()})
		return true
	}
	if r.Method != "PUT" && r.Method != "DELETE" {
		reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	var input struct {
		Revision string `json:"revision"`
		APIKey   string `json:"apiKey"`
	}
	if decodeBody(w, r, &input) != nil {
		reject(w, 400, "INVALID_MODEL_GATEWAY_KEY")
		return true
	}
	if s.applying || input.Revision != s.value.Revision {
		reject(w, 409, "MODEL_CATALOG_CHANGED")
		return true
	}
	next := s.snapshot()
	if r.Method == "DELETE" {
		next.AccessKey = gatewayAccessKey{}
	} else {
		if !validGatewayAccessKey(input.APIKey) {
			reject(w, 400, "INVALID_MODEL_GATEWAY_KEY")
			return true
		}
		if s.reservedAgentCredential(input.APIKey) {
			reject(w, 400, "MODEL_GATEWAY_KEY_RESERVED")
			return true
		}
		id, err := randomCatalogID()
		if err != nil {
			reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			return true
		}
		sum := sha256.Sum256([]byte(input.APIKey))
		next.AccessKey = gatewayAccessKey{Hash: hex.EncodeToString(sum[:]), ID: id, Suffix: input.APIKey[len(input.APIKey)-8:], Updated: s.ledger.now().UnixMilli()}
	}
	if s.persist(next) != nil {
		reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		return true
	}
	writeJSON(w, 200, map[string]any{"data": s.accessKeyView()})
	return true
}
