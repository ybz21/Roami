package modelgateway

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"

	"github.com/ybz21/Roami/internal/agentruntime"
)

func (s *CatalogStore) runtimeModels(r *http.Request, method string, patch map[string]any) (map[string]any, error) {
	var body []byte
	var err error
	if patch != nil {
		body, err = json.Marshal(patch)
		if err != nil {
			return nil, err
		}
	}
	request, err := http.NewRequestWithContext(r.Context(), method, "http://roami-agent/v1/model-settings", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	request.Header.Set("Content-Type", "application/json")
	request.Header.Set("X-Roami-Owner", "local")
	transport := agentruntime.Transport(s.agentSocket)
	defer transport.CloseIdleConnections()
	response, err := (&http.Client{Transport: transport}).Do(request)
	if err != nil {
		return nil, errors.New("MODEL_GATEWAY_UNAVAILABLE")
	}
	defer response.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(response.Body, 64<<10))
	if err != nil {
		return nil, err
	}
	var result struct {
		Data  map[string]any `json:"data"`
		Error struct {
			Code string `json:"code"`
		} `json:"error"`
	}
	if json.Unmarshal(raw, &result) != nil {
		return nil, errors.New("MODEL_GATEWAY_UNAVAILABLE")
	}
	if response.StatusCode != 200 {
		if result.Error.Code != "" {
			return nil, errors.New(result.Error.Code)
		}
		return nil, errors.New("MODEL_GATEWAY_UNAVAILABLE")
	}
	return result.Data, nil
}

func (h *Handler) applyRoamiModels(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Main     string `json:"main"`
		Worker   string `json:"worker"`
		Revision string `json:"revision"`
		Restore  bool   `json:"restore"`
	}
	if decodeBody(w, r, &input) != nil {
		reject(w, 400, "INVALID_MODEL_CATALOG")
		return
	}
	s := h.Catalog
	s.mu.Lock()
	if s.applying || input.Revision != s.value.Revision {
		s.mu.Unlock()
		reject(w, 409, "MODEL_CATALOG_CHANGED")
		return
	}
	if !input.Restore {
		for _, name := range []string{input.Main, input.Worker} {
			valid := false
			for _, model := range s.value.Models {
				if model.ID == name && model.Protocol == "openai-completions" {
					valid = true
				}
			}
			if !valid {
				s.mu.Unlock()
				reject(w, 400, "INVALID_MODEL_PROTOCOL")
				return
			}
		}
	}
	backup := s.value.RolesBackup
	if input.Restore && backup == nil {
		s.mu.Unlock()
		reject(w, 409, "AGENT_CONFIG_RESTORE_UNAVAILABLE")
		return
	}
	s.applying = true
	key, base := s.credential("roami"), s.baseURL+"/v1"
	s.mu.Unlock()
	defer func() { s.mu.Lock(); s.applying = false; s.mu.Unlock() }()
	if !input.Restore && backup == nil {
		main, e1 := readNodeModels(s.ledger.paths, "main")
		worker, e2 := readNodeModels(s.ledger.paths, "worker")
		if e1 == nil && e2 == nil {
			if main.endpoint != worker.endpoint || main.key != worker.key {
				reject(w, 409, "INVALID_MODEL_CONFIG")
				return
			}
			current, err := s.runtimeModels(r, "GET", nil)
			if err != nil {
				reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
				return
			}
			backup = map[string]any{"connection": map[string]any{"baseUrl": main.endpoint, "apiKey": main.key}}
			for _, role := range []string{"main", "worker"} {
				row, _ := current[role].(map[string]any)
				saved := map[string]any{}
				for _, field := range []string{"model", "images", "reasoningEffort"} {
					if value, ok := row[field]; ok {
						saved[field] = value
					}
				}
				saved["contextWindow"] = row["configuredContextWindow"]
				backup[role] = saved
			}
			s.mu.Lock()
			next := s.snapshot()
			next.RolesBackup = backup
			err = s.persist(next)
			s.mu.Unlock()
			if err != nil {
				reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
				return
			}
		}
	}
	patch := backup
	if !input.Restore {
		patch = map[string]any{"connection": map[string]any{"baseUrl": base, "apiKey": key}, "main": map[string]any{"model": input.Main, "images": false, "contextWindow": nil, "reasoningEffort": nil}, "worker": map[string]any{"model": input.Worker, "images": false, "contextWindow": nil, "reasoningEffort": nil}}
	}
	if _, err := s.runtimeModels(r, "PUT", patch); err != nil {
		reject(w, 503, err.Error())
		return
	}
	s.mu.Lock()
	if err := s.persist(s.snapshot()); err != nil {
		s.mu.Unlock()
		reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		return
	}
	view := s.view(r.Context())
	s.mu.Unlock()
	writeJSON(w, 200, map[string]any{"data": view})
}
