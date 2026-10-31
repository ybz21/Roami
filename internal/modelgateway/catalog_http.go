package modelgateway

import (
	"bytes"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"strconv"
	"strings"

	"github.com/ybz21/Roami/internal/agentproviders"
)

func (h *Handler) catalogManagement(w http.ResponseWriter, r *http.Request) bool {
	if !strings.HasPrefix(r.URL.Path, "/v1/model-gateway/catalog") {
		return false
	}
	if h.Catalog == nil {
		reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return true
	}
	if r.URL.Path == "/v1/model-gateway/catalog/roles" && r.Method == "POST" {
		h.applyRoamiModels(w, r)
		return true
	}
	if r.URL.Path == "/v1/model-gateway/catalog/source-models" && r.Method == "POST" {
		h.sourceModels(w, r)
		return true
	}
	s := h.Catalog
	s.mu.Lock()
	defer s.mu.Unlock()
	var err error
	switch {
	case r.URL.Path == "/v1/model-gateway/catalog" && r.Method == "GET":
		writeJSON(w, 200, map[string]any{"data": s.view(r.Context())})
		return true
	case r.URL.Path == "/v1/model-gateway/catalog" && r.Method == "PUT":
		var value ModelCatalog
		decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
		decoder.DisallowUnknownFields()
		if decoder.Decode(&value) != nil || decoder.Decode(new(any)) != io.EOF {
			reject(w, 400, "INVALID_MODEL_CATALOG")
			return true
		}
		err = s.update(r.Context(), value)
		if err == nil {
			writeJSON(w, 200, map[string]any{"data": s.view(r.Context())})
			return true
		}
	case r.URL.Path == "/v1/model-gateway/catalog/apply" && r.Method == "POST":
		var input struct {
			Kind            string `json:"kind"`
			SourceID        string `json:"sourceId"`
			UpstreamModel   string `json:"upstreamModel"`
			Model           string `json:"model"`
			Revision        string `json:"revision"`
			CatalogRevision string `json:"catalogRevision"`
		}
		if decodeBody(w, r, &input) != nil {
			reject(w, 400, "INVALID_MODEL_CATALOG")
			return true
		}
		if input.CatalogRevision != s.value.Revision {
			err = errors.New("MODEL_CATALOG_CHANGED")
			break
		}
		var model *CatalogModel
		for _, m := range s.value.Models {
			if m.ID == input.Model {
				copy := m
				model = &copy
			}
		}
		created := false
		if input.UpstreamModel != "" {
			upstream := strings.TrimSpace(input.UpstreamModel)
			var source *ModelSource
			for _, row := range s.value.Sources {
				if row.ID == input.SourceID {
					copy := row
					source = &copy
				}
			}
			if input.Model != "" || source == nil || upstream == "" || upstream == source.APIKey || len(upstream) > 200 || strings.ContainsAny(upstream, "\r\n\x00") || !catalogProtocol(input.Kind, source.Protocol) {
				err = catalogError()
				break
			}
			for _, row := range s.value.Models {
				if row.Protocol == source.Protocol && row.Candidates[0].SourceID == source.ID && row.Candidates[0].Model == upstream {
					copy := row
					model = &copy
					break
				}
			}
			if model == nil {
				if len(s.value.Models) >= 200 {
					err = catalogError()
					break
				}
				id, e := randomCatalogID()
				if e != nil {
					err = e
					break
				}
				model = &CatalogModel{ID: id, Name: upstream, Protocol: source.Protocol, Strategy: "fixed", Candidates: []ModelCandidate{{SourceID: source.ID, Model: upstream}}}
				created = true
			}
		}
		if model == nil || input.SourceID != "" && model.Candidates[0].SourceID != input.SourceID {
			err = catalogError()
			break
		}
		if !catalogProtocol(input.Kind, model.Protocol) {
			err = errors.New("INVALID_MODEL_PROTOCOL")
			break
		}
		view, e := s.agents.View(r.Context(), input.Kind)
		if e != nil {
			err = e
			break
		}
		if view.Revision != input.Revision {
			err = errors.New("AGENT_CONFIG_CHANGED")
			break
		}
		if created {
			next := s.snapshot()
			next.Models = append(next.Models, *model)
			if err = s.persist(next); err != nil {
				break
			}
		}
		key := s.credential(input.Kind)
		base := s.baseURL + "/v1"
		if model.Protocol == "anthropic-messages" {
			base = s.baseURL
		}
		profileID := ""
		for _, p := range view.Profiles {
			if p.Name == "Roami Gateway" && p.BaseURL == base {
				profileID = p.ID
			}
		}
		authMode := "api_key"
		if input.Kind == "claude" {
			authMode = "bearer"
		}
		profile, e := s.agents.Save(r.Context(), input.Kind, profileID, agentproviders.ProfileInput{Name: "Roami Gateway", BaseURL: base, Model: model.ID, Protocol: model.Protocol, AuthMode: authMode, APIKey: &key})
		if e != nil {
			err = e
			break
		}
		// Non-Claude adapters accept API-key credentials, with bearer transport handled by the CLI.
		_, err = s.agents.Apply(r.Context(), input.Kind, profile.ID, input.Revision)
		if err == nil {
			writeJSON(w, 200, map[string]any{"data": s.view(r.Context())})
			return true
		}
	default:
		reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return true
	}
	status := 400
	if err != nil && containsField([]string{"MODEL_CATALOG_CHANGED", "MODEL_CATALOG_IN_USE", "AGENT_CONFIG_CHANGED", "AGENT_CONFIG_INLINE_OVERRIDE", "AGENT_CONFIG_RECOVERY_REQUIRED", "OPENCODE_CONFIG_VERSION_UNKNOWN"}, err.Error()) {
		status = 409
	}
	if err == nil {
		err = catalogError()
	}
	reject(w, status, err.Error())
	return true
}

// Only this handler is mounted on loopback; management stays on the private Unix socket.
func (h *Handler) publicModels(w http.ResponseWriter, r *http.Request) {
	h.mu.Lock()
	if h.closing {
		h.mu.Unlock()
		reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return
	}
	h.wait.Add(1)
	h.mu.Unlock()
	defer h.wait.Done()
	s := h.Catalog
	s.mu.Lock()
	kind := ""
	key := strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer ")
	if key == "" {
		key = r.Header.Get("X-Api-Key")
	}
	for _, candidate := range []string{"codex", "claude", "opencode", "pi", "roami"} {
		if subtle.ConstantTimeCompare([]byte(key), []byte(s.credential(candidate))) == 1 {
			kind = candidate
		}
	}
	snapshot := s.snapshot()
	s.mu.Unlock()
	if kind == "" {
		reject(w, 401, "MODEL_GATEWAY_UNAUTHORIZED")
		return
	}
	if r.Method == "GET" && r.URL.Path == "/v1/models" {
		data := []map[string]any{}
		for _, m := range snapshot.Models {
			if kind == "codex" && m.Protocol != "openai-responses" || kind == "claude" && m.Protocol != "anthropic-messages" || kind == "roami" && m.Protocol != "openai-completions" {
				continue
			}
			data = append(data, map[string]any{"id": m.ID, "type": "model", "object": "model", "display_name": m.Name, "owned_by": "roami"})
		}
		writeJSON(w, 200, map[string]any{"object": "list", "data": data, "has_more": false})
		return
	}
	protocol := ""
	switch r.URL.Path {
	case "/v1/responses", "/v1/responses/compact":
		protocol = "openai-responses"
	case "/v1/messages":
		protocol = "anthropic-messages"
	case "/v1/chat/completions":
		protocol = "openai-completions"
	}
	if protocol == "" || r.Method != "POST" {
		reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
		return
	}
	if kind == "codex" && protocol != "openai-responses" || kind == "claude" && protocol != "anthropic-messages" || kind == "roami" && protocol != "openai-completions" {
		reject(w, 400, "INVALID_MODEL_PROTOCOL")
		return
	}
	h.forwardCatalog(w, r, snapshot, kind, protocol)
}

func (h *Handler) forwardCatalog(w http.ResponseWriter, r *http.Request, catalog ModelCatalog, kind, protocol string, checks ...func() error) {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 32<<20))
	var payload map[string]json.RawMessage
	if err != nil || json.Unmarshal(body, &payload) != nil {
		reject(w, 400, "INVALID_MODEL_CONFIG")
		return
	}
	var alias string
	_ = json.Unmarshal(payload["model"], &alias)
	var model *CatalogModel
	for _, m := range catalog.Models {
		if m.ID == alias && m.Protocol == protocol {
			copy := m
			model = &copy
		}
	}
	if model == nil {
		reject(w, 400, "MODEL_NOT_CONFIGURED")
		return
	}
	// Stateful provider IDs are not portable across sources or policy revisions.
	if raw := payload["previous_response_id"]; len(raw) > 0 && string(raw) != "null" {
		reject(w, 400, "MODEL_GATEWAY_CONTINUATION_UNSUPPORTED")
		return
	}
	sources := map[string]ModelSource{}
	for _, s := range catalog.Sources {
		sources[s.ID] = s
	}
	for index, candidate := range model.Candidates {
		source := sources[candidate.SourceID]
		validate := func() error { return nil }
		if len(checks) > 0 {
			validate = checks[0]
		}
		role, session := "cli_"+kind, ""
		if strings.HasPrefix(kind, "roami_") {
			role = strings.TrimPrefix(kind, "roami_")
			session = r.Header.Get("X-Eval-Session-Id")
			if observed := r.Header.Get("X-Eval-Call-Role"); observed != "" {
				role = observed
			}
		}
		if len(role) > 100 || len(session) > 200 || len(r.Header.Get("X-Request-Id")) > 200 {
			reject(w, 400, "INVALID_MODEL_CONFIG")
			return
		}
		call, e := h.admit(r.Context(), role, candidate.Model, session, r.Header.Get("X-Request-Id"), validate)
		if e != nil {
			status := 503
			if e.Error() == "MODEL_PROXY_DAILY_LIMIT" {
				status = 402
			}
			if strings.HasPrefix(e.Error(), "MODEL_PROXY_USAGE_") {
				status = 409
			}
			reject(w, status, e.Error())
			return
		}
		status, code, notSent := 0, "MODEL_GATEWAY_INTERRUPTED", false
		var usage *Usage
		// Each attempted source settles independently, including zero-send connection failures.
		attempt := func() bool {
			defer func() {
				if err := h.Ledger.Settle(call, usage, status, code, notSent); err != nil {
					log.Printf("model gateway: settlement failed call=%s", call.ID)
				}
				h.releaseAdmission()
			}()
			payload["model"], _ = json.Marshal(candidate.Model)
			upstreamBody, _ := json.Marshal(payload)
			suffix := r.URL.Path
			if strings.HasSuffix(source.BaseURL, "/v1") {
				suffix = strings.TrimPrefix(suffix, "/v1")
			}
			out, e := http.NewRequestWithContext(r.Context(), "POST", source.BaseURL+suffix, bytes.NewReader(upstreamBody))
			if e != nil {
				notSent = true
				code = "INVALID_MODEL_CONFIG"
				reject(w, 400, code)
				return false
			}
			for name, values := range r.Header {
				lower := strings.ToLower(name)
				if containsField([]string{"authorization", "cookie", "x-api-key", "api-key", "proxy-authorization", "connection", "upgrade", "content-length", "host"}, lower) || strings.HasPrefix(lower, "x-roami-") {
					continue
				}
				out.Header[name] = append([]string(nil), values...)
			}
			out.Header.Set("Content-Type", "application/json")
			if source.APIKey != "" {
				if protocol == "anthropic-messages" && source.AuthMode == "api_key" {
					out.Header.Set("X-Api-Key", source.APIKey)
				} else {
					out.Header.Set("Authorization", "Bearer "+source.APIKey)
				}
			}
			response, e := h.Client.Do(out)
			if e != nil {
				var op *net.OpError
				notSent = errors.As(e, &op) && op.Op == "dial"
				code = "MODEL_TRANSPORT_FAILED"
				if notSent && model.Strategy == "failover" && index+1 < len(model.Candidates) && r.Context().Err() == nil {
					return true
				}
				reject(w, 502, code)
				return false
			}
			defer response.Body.Close()
			status = response.StatusCode
			for name, values := range response.Header {
				lower := strings.ToLower(name)
				if containsField([]string{"connection", "transfer-encoding", "content-length", "set-cookie", "upgrade"}, lower) {
					continue
				}
				w.Header()[name] = append([]string(nil), values...)
			}
			w.Header().Set("X-Roami-Model-Source", source.ID)
			w.Header().Set("X-Roami-Model-Alias", model.ID)
			w.Header().Set("X-Roami-Model-Call", call.ID)
			w.WriteHeader(status)
			capture := nativeUsageCapture{protocol: protocol, stream: strings.Contains(response.Header.Get("Content-Type"), "text/event-stream")}
			buffer := make([]byte, 32<<10)
			complete := false
			for {
				n, re := response.Body.Read(buffer)
				if n > 0 {
					capture.feed(buffer[:n])
					if _, e = w.Write(buffer[:n]); e != nil {
						break
					}
					if capture.stream {
						if f, ok := w.(http.Flusher); ok {
							f.Flush()
						}
					}
				}
				if re != nil {
					complete = re == io.EOF
					break
				}
			}
			if status >= 200 && status < 300 {
				usage = capture.finish(complete)
				if usage != nil {
					code = ""
				} else {
					code = "MODEL_PROXY_USAGE_UNKNOWN"
				}
			} else {
				code = "MODEL_HTTP_" + strconv.Itoa(status)
			}
			return false
		}
		if !attempt() {
			return
		}
	}
}
