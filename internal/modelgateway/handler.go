package modelgateway

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/http"
	"strconv"
	"strings"
	"sync"
)

type Handler struct {
	Catalog          *CatalogStore
	Ledger           *Ledger
	Client           *http.Client
	wait             sync.WaitGroup
	mu               sync.Mutex
	closing          bool
	activeForwards   int
	admissionChanged chan struct{}
}

func NewHandler(ledger *Ledger) *Handler {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	return &Handler{Ledger: ledger, Client: &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func reject(w http.ResponseWriter, status int, code string) {
	w.Header().Set("X-Roami-Model-Error", code)
	writeJSON(w, status, map[string]any{"error": map[string]string{"code": code}})
}

func decodeBody(w http.ResponseWriter, r *http.Request, value any) error {
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(value); err != nil {
		return err
	}
	if decoder.Decode(new(any)) != io.EOF {
		return errors.New("trailing JSON")
	}
	return nil
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.mu.Lock()
	if h.closing {
		h.mu.Unlock()
		reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return
	}
	h.wait.Add(1)
	h.mu.Unlock()
	defer h.wait.Done()
	if h.agentKeysManagement(w, r) || h.catalogManagement(w, r) {
		return
	}
	if r.Method == "POST" && r.URL.Path == "/v1/chat/completions" {
		h.forward(w, r)
		return
	}
	if r.URL.Path == "/v1/model-gateway/settings" {
		switch r.Method {
		case "GET":
			c, err := h.Ledger.Configuration()
			if err != nil {
				reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
				return
			}
			writeJSON(w, 200, map[string]any{"data": c})
			return
		case "PUT":
			c := defaultConfiguration()
			c.Pricing.DefaultConfigured = nil
			if decodeBody(w, r, &c) != nil || c.validate() != nil {
				reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
				return
			}
			if err := h.Ledger.Configure(c); err != nil {
				if err.Error() == "MODEL_PROXY_CURRENCY_MISMATCH" {
					reject(w, 409, err.Error())
				} else {
					reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
				}
				return
			}
			h.notifyAdmission()
			writeJSON(w, 200, map[string]any{"data": c})
			return
		}
	}
	if r.Method == "GET" && r.URL.Path == "/v1/model-gateway/usage" {
		days := 7
		if raw := r.URL.Query().Get("days"); raw != "" {
			var parseErr error
			days, parseErr = strconv.Atoi(raw)
			if parseErr != nil {
				reject(w, 400, "INVALID_MODEL_USAGE_DAY")
				return
			}
		}
		if days < 0 || days > 90 {
			reject(w, 400, "INVALID_MODEL_USAGE_DAY")
			return
		}
		data, err := h.Ledger.StatisticsForSource(days, r.URL.Query().Get("day"), r.URL.Query().Get("source"), r.URL.Query().Get("agentKind"))
		if err != nil {
			if err.Error() == "INVALID_MODEL_USAGE_DAY" || err.Error() == "INVALID_MODEL_USAGE_SOURCE" || err.Error() == "INVALID_AGENT_KIND" {
				reject(w, 400, err.Error())
				return
			}
			reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			return
		}
		writeJSON(w, 200, map[string]any{"data": data})
		return
	}
	if r.Method == "PUT" && strings.HasPrefix(r.URL.Path, "/v1/model-gateway/calls/") {
		id := strings.TrimPrefix(r.URL.Path, "/v1/model-gateway/calls/")
		var value struct {
			Amount *float64 `json:"amount"`
			Reason string   `json:"reason"`
		}
		if strings.Contains(id, "/") || decodeBody(w, r, &value) != nil || value.Amount == nil || !validAmount(*value.Amount) || strings.TrimSpace(value.Reason) == "" || len(value.Reason) > 500 {
			reject(w, 400, "INVALID_MODEL_PROXY_CONFIG")
			return
		}
		if err := h.Ledger.Reconcile(id, *value.Amount, value.Reason); err != nil {
			if err.Error() == "MODEL_GATEWAY_CALL_NOT_UNKNOWN" {
				reject(w, 409, err.Error())
			} else {
				reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
			}
			return
		}
		writeJSON(w, 200, map[string]any{"data": map[string]string{"id": id}})
		return
	}
	reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
}

func (h *Handler) forward(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 256<<20))
	var payload struct {
		Model  string `json:"model"`
		Stream bool   `json:"stream"`
	}
	if err != nil || json.Unmarshal(body, &payload) != nil || len(payload.Model) == 0 || len(payload.Model) > 200 {
		reject(w, 400, "INVALID_MODEL_CONFIG")
		return
	}
	routingRole := r.Header.Get("X-Roami-Model-Role")
	if routingRole == "" {
		routingRole = "main"
	}
	if h.Catalog != nil {
		configured, e := readNodeModels(h.Ledger.paths, routingRole)
		if e == nil && configured.endpoint == h.Catalog.baseURL+"/v1" {
			var requested map[string]any
			_ = json.Unmarshal(body, &requested)
			check := func() error {
				current, err := readNodeModels(h.Ledger.paths, routingRole)
				if err != nil {
					return err
				}
				if current.endpoint != h.Catalog.baseURL+"/v1" || !current.accepts(requested, r.Header.Get("X-Roami-Model-Route")) {
					return errors.New("MODEL_GATEWAY_ROUTE_CHANGED")
				}
				return nil
			}
			if err := check(); err != nil {
				reject(w, 409, err.Error())
				return
			}
			h.Catalog.mu.Lock()
			if h.Catalog.value.AgentKeys["roami"].Disabled {
				h.Catalog.mu.Unlock()
				reject(w, 403, "MODEL_GATEWAY_KEY_DISABLED")
				return
			}
			keyID := keyID(h.Catalog.value.AgentKeys["roami"].ID)
			snapshot := h.Catalog.snapshot()
			h.Catalog.mu.Unlock()
			r.Body = io.NopCloser(bytes.NewReader(body))
			r = r.WithContext(context.WithValue(r.Context(), gatewayKeyContext{}, keyID))
			h.forwardCatalog(w, r, snapshot, "roami_"+routingRole, "openai-completions", check)
			return
		}
	}
	var route nodeModelRoute
	var requestBody map[string]any
	_ = json.Unmarshal(body, &requestBody)
	validate := func() error {
		var routeErr error
		route, routeErr = readNodeModels(h.Ledger.paths, routingRole)
		if routeErr != nil {
			return routeErr
		}
		if !route.accepts(requestBody, r.Header.Get("X-Roami-Model-Route")) {
			return errors.New("MODEL_GATEWAY_ROUTE_CHANGED")
		}
		return nil
	}
	role := r.Header.Get("X-Roami-Model-Role")
	if observed := r.Header.Get("X-Eval-Call-Role"); observed != "" {
		role = observed
	}
	if role == "" {
		role = "main"
	}
	session, requestID := r.Header.Get("X-Eval-Session-Id"), r.Header.Get("X-Request-Id")
	if len(role) > 100 || len(session) > 200 || len(requestID) > 200 {
		reject(w, 400, "INVALID_MODEL_CONFIG")
		return
	}
	call, err := h.admit(r.Context(), role, payload.Model, session, requestID, validate)
	if err != nil {
		if r.Context().Err() != nil {
			return
		}
		switch err.Error() {
		case "MODEL_PROXY_DAILY_LIMIT":
			reject(w, 402, err.Error())
		case "MODEL_PROXY_USAGE_PENDING", "MODEL_PROXY_USAGE_UNKNOWN":
			reject(w, 409, err.Error())
		case "MODEL_GATEWAY_ROUTE_CHANGED":
			reject(w, 409, err.Error())
		case "MODEL_NOT_CONFIGURED", "MODEL_GATEWAY_CONFIGURATION_INVALID", "INVALID_MODEL_CONFIG", "MODEL_GATEWAY_UNAVAILABLE":
			reject(w, 503, err.Error())
		default:
			reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		}
		return
	}
	w.Header().Set("X-Roami-Model-Call", call.ID)
	status, code, notSent := 0, "MODEL_GATEWAY_INTERRUPTED", false
	var usage *Usage
	defer func() {
		defer h.releaseAdmission()
		if err := h.Ledger.Settle(call, usage, status, code, notSent); err != nil {
			log.Printf("model gateway: settlement failed call=%s", call.ID)
		}
	}()
	out, err := http.NewRequestWithContext(r.Context(), "POST", route.endpoint+"/chat/completions", bytes.NewReader(body))
	if err != nil {
		notSent = true
		reject(w, 400, "INVALID_MODEL_CONFIG")
		return
	}
	for key, values := range r.Header {
		if strings.HasPrefix(strings.ToLower(key), "x-roami-") || key == "Cookie" || key == "Connection" || key == "Proxy-Authorization" || key == "Authorization" || strings.EqualFold(key, "X-Api-Key") || strings.EqualFold(key, "Api-Key") {
			continue
		}
		out.Header[key] = append([]string(nil), values...)
	}
	if route.key != "" {
		out.Header.Set("Authorization", "Bearer "+route.key)
	}
	response, err := h.Client.Do(out)
	if err != nil {
		var op *net.OpError
		notSent = errors.As(err, &op) && op.Op == "dial"
		code = "MODEL_TRANSPORT_FAILED"
		reject(w, 502, code)
		return
	}
	defer response.Body.Close()
	status = response.StatusCode
	for _, key := range []string{"Content-Type", "Cache-Control", "Retry-After", "X-Request-Id", "Request-Id"} {
		if value := response.Header.Get(key); value != "" {
			w.Header().Set(key, value)
		}
	}
	w.WriteHeader(status)
	capture := usageCapture{stream: strings.Contains(response.Header.Get("Content-Type"), "text/event-stream")}
	buffer := make([]byte, 32<<10)
	complete := false
	for {
		n, readErr := response.Body.Read(buffer)
		if n > 0 {
			capture.feed(buffer[:n])
			if _, err = w.Write(buffer[:n]); err != nil {
				break
			}
			if capture.stream {
				if f, ok := w.(http.Flusher); ok {
					f.Flush()
				}
			}
		}
		if readErr != nil {
			complete = readErr == io.EOF
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
		notSent = complete && status >= 300 && status < 500
	}
}
