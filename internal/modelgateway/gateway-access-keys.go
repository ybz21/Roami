package modelgateway

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"net/http"
	"strings"
	"unicode"
)

func externalKeyGeneration(key gatewayAccessKey) string {
	if key.Generation != "" {
		return key.Generation
	}
	return key.ID
}
func (s *CatalogStore) externalKeys() []gatewayAccessKey {
	keys := append([]gatewayAccessKey(nil), s.value.AccessKeys...)
	if s.value.AccessKey.Hash != "" {
		keys = append(keys, s.value.AccessKey)
	}
	return keys
}
func validStoredGatewayAccessKeys(keys []gatewayAccessKey) bool {
	if len(keys) > 100 {
		return false
	}
	seen := map[string]bool{}
	for _, key := range keys {
		if key.Hash == "" || !validStoredGatewayAccessKey(key) || seen[key.ID] || !validGatewayKeyName(key.Name) {
			return false
		}
		if key.Generation != "" {
			generation, err := hex.DecodeString(key.Generation)
			if err != nil || len(generation) != 24 {
				return false
			}
		}
		seen[key.ID] = true
	}
	return true
}
func validGatewayKeyName(name string) bool {
	if strings.TrimSpace(name) == "" || len([]rune(name)) > 80 {
		return false
	}
	for _, r := range name {
		if unicode.IsControl(r) {
			return false
		}
	}
	return true
}
func (s *CatalogStore) accessKeysView() map[string]any {
	rows := []map[string]any{}
	for _, key := range s.externalKeys() {
		rows = append(rows, map[string]any{"id": key.ID, "name": key.Name, "suffix": key.Suffix, "disabled": key.Disabled, "createdMs": key.Created, "updatedMs": key.Updated})
	}
	return map[string]any{"revision": s.value.Revision, "keys": rows}
}
func (h *Handler) accessKeysManagement(w http.ResponseWriter, r *http.Request) bool {
	const route = "/v1/model-gateway/access-keys"
	if r.URL.Path != route && !strings.HasPrefix(r.URL.Path, route+"/") {
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
	if r.Method == "GET" && r.URL.Path == route {
		writeJSON(w, 200, map[string]any{"data": s.accessKeysView()})
		return true
	}
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, route+"/"), "/")
	create := r.URL.Path == route && r.Method == "POST"
	rotate := len(parts) == 2 && parts[1] == "rotate" && r.Method == "POST"
	edit := len(parts) == 1 && r.URL.Path != route && r.Method == "PATCH"
	remove := len(parts) == 1 && r.URL.Path != route && r.Method == "DELETE"
	if !create && !rotate && !edit && !remove {
		reject(w, 405, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	var input struct {
		Revision string  `json:"revision"`
		Name     *string `json:"name"`
		Disabled *bool   `json:"disabled"`
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
	var target *gatewayAccessKey
	index := -1
	legacy := false
	if create {
		if len(s.externalKeys()) >= 100 {
			reject(w, 400, "MODEL_GATEWAY_KEY_LIMIT")
			return true
		}
		if input.Name == nil || !validGatewayKeyName(*input.Name) {
			reject(w, 400, "INVALID_MODEL_GATEWAY_KEY")
			return true
		}
		id, err := randomCatalogID()
		if err != nil {
			reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			return true
		}
		next.AccessKeys = append(next.AccessKeys, gatewayAccessKey{ID: id, Name: strings.TrimSpace(*input.Name), Created: s.ledger.now().UnixMilli()})
		target = &next.AccessKeys[len(next.AccessKeys)-1]
	} else {
		if next.AccessKey.Hash != "" && parts[0] == next.AccessKey.ID {
			target = &next.AccessKey
			legacy = true
		} else {
			for i := range next.AccessKeys {
				if next.AccessKeys[i].ID == parts[0] {
					target = &next.AccessKeys[i]
					index = i
					break
				}
			}
		}
		if target == nil {
			reject(w, 404, "MODEL_GATEWAY_KEY_NOT_FOUND")
			return true
		}
	}
	secret := ""
	if create || rotate {
		var bytes [32]byte
		if _, err := rand.Read(bytes[:]); err != nil {
			reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			return true
		}
		generation, err := randomCatalogID()
		if err != nil {
			reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			return true
		}
		secret = "sk-roami-" + base64.RawURLEncoding.EncodeToString(bytes[:])
		sum := sha256.Sum256([]byte(secret))
		target.Hash = hex.EncodeToString(sum[:])
		target.Generation = generation
		target.Suffix = secret[len(secret)-8:]
	}
	if edit {
		if input.Name == nil && input.Disabled == nil {
			reject(w, 400, "INVALID_MODEL_GATEWAY_KEY")
			return true
		}
		if input.Name != nil {
			if !validGatewayKeyName(*input.Name) {
				reject(w, 400, "INVALID_MODEL_GATEWAY_KEY")
				return true
			}
			target.Name = strings.TrimSpace(*input.Name)
		}
		if input.Disabled != nil {
			target.Disabled = *input.Disabled
		}
	}
	target.Updated = s.ledger.now().UnixMilli()
	if remove {
		if legacy {
			next.AccessKey = gatewayAccessKey{}
		} else {
			next.AccessKeys = append(next.AccessKeys[:index], next.AccessKeys[index+1:]...)
		}
	}
	if s.persist(next) != nil {
		reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		return true
	}
	result := s.accessKeysView()
	if secret != "" {
		result["apiKey"] = secret
	}
	writeJSON(w, 200, map[string]any{"data": result})
	return true
}
