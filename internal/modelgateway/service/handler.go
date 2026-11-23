package service

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
	"time"

	"github.com/ybz21/Roami/internal/modelgateway/accounting"
	"github.com/ybz21/Roami/internal/modelgateway/hostroute"
	"github.com/ybz21/Roami/internal/modelgateway/httpapi"
	"github.com/ybz21/Roami/internal/modelgateway/monitor"
	"github.com/ybz21/Roami/internal/modelgateway/protocol"
	"github.com/ybz21/Roami/internal/modelgateway/routing"
	"github.com/ybz21/Roami/internal/modelgateway/upstream"
	"github.com/ybz21/Roami/internal/modelplugins"
)

type Handler struct {
	routing        routing.Selector
	Monitor        *monitor.Store
	Plugins        *modelplugins.Manager
	Catalog        *CatalogStore
	network        networkSettings
	state          *gatewayState
	Client         *http.Client
	uncheckedTLS   *http.Client
	wait           sync.WaitGroup
	mu             sync.Mutex
	closing        bool
	activeForwards int
	admissionQueue []*admissionWaiter
}

func NewHandler(ledger *gatewayState) *Handler {
	verified, unchecked := upstream.NewClients()
	return &Handler{state: ledger, Client: verified, uncheckedTLS: unchecked}
}

func (h *Handler) sourceClient(source ModelSource) *http.Client {
	client := h.Client
	if source.SkipTLSVerification {
		client = h.uncheckedTLS
	}
	return upstream.WithHeaders(client, source.BaseURL, source.Headers)
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.mu.Lock()
	if h.closing {
		h.mu.Unlock()
		httpapi.Reject(w, 503, "MODEL_GATEWAY_UNAVAILABLE")
		return
	}
	h.wait.Add(1)
	h.mu.Unlock()
	defer h.wait.Done()
	if h.gatewayNetworkManagement(w, r) || h.modelDirectoryManagement(w, r) || h.sourcePricingManagement(w, r) || h.monitorManagement(w, r) || h.pluginsManagement(w, r) || h.accessKeysManagement(w, r) || h.accessKeyManagement(w, r) || h.agentKeysManagement(w, r) || h.catalogManagement(w, r) {
		return
	}
	if r.Method == "POST" && r.URL.Path == "/v1/chat/completions" {
		h.forward(w, r)
		return
	}
	if h.state != nil && httpapi.ServeAccounting(w, r, h.state.accounting, h.notifyAdmission) {
		return
	}
	httpapi.Reject(w, 404, "MODEL_GATEWAY_ROUTE_NOT_FOUND")
}

func (h *Handler) forward(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 256<<20))
	var payload struct {
		Model    string `json:"model"`
		Stream   bool   `json:"stream"`
		FreeOnly bool   `json:"roami_free_only"`
	}
	if err != nil || json.Unmarshal(body, &payload) != nil || len(payload.Model) == 0 || len(payload.Model) > 200 {
		httpapi.Reject(w, 400, "INVALID_MODEL_CONFIG")
		return
	}
	if payload.FreeOnly && h.Catalog == nil {
		httpapi.Reject(w, 503, "MODEL_GATEWAY_REQUIRED")
		return
	}
	routingRole := r.Header.Get("X-Roami-Model-Role")
	if routingRole == "" {
		routingRole = "main"
	}
	if h.Catalog != nil {
		configured, e := hostroute.Read(h.state.paths, routingRole)
		if e == nil && (configured.Endpoint == h.Catalog.baseURL+"/v1" || payload.Model != configured.Model || payload.FreeOnly) {
			var requested map[string]any
			_ = json.Unmarshal(body, &requested)
			requested["model"] = configured.Model
			check := func() error {
				current, err := hostroute.Read(h.state.paths, routingRole)
				if err != nil {
					return err
				}
				if !current.Accepts(requested, r.Header.Get("X-Roami-Model-Route")) {
					return errors.New("MODEL_GATEWAY_ROUTE_CHANGED")
				}
				return nil
			}
			if err := check(); err != nil {
				httpapi.Reject(w, 409, err.Error())
				return
			}
			h.Catalog.mu.Lock()
			if h.Catalog.value.AgentKeys["roami"].Disabled {
				h.Catalog.mu.Unlock()
				httpapi.Reject(w, 403, "MODEL_GATEWAY_KEY_DISABLED")
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
	var route hostroute.Route
	var requestBody map[string]any
	_ = json.Unmarshal(body, &requestBody)
	validate := func() error {
		var routeErr error
		route, routeErr = hostroute.Read(h.state.paths, routingRole)
		if routeErr != nil {
			return routeErr
		}
		if !route.Accepts(requestBody, r.Header.Get("X-Roami-Model-Route")) {
			return errors.New("MODEL_GATEWAY_ROUTE_CHANGED")
		}
		return nil
	}
	role := r.Header.Get("X-Roami-Model-Role")
	if observed := r.Header.Get("X-Eval-accounting.Call-Role"); observed != "" {
		role = observed
	}
	if role == "" {
		role = "main"
	}
	session, requestID := r.Header.Get("X-Eval-Session-Id"), r.Header.Get("X-Request-Id")
	if len(role) > 100 || len(session) > 200 || len(requestID) > 200 {
		httpapi.Reject(w, 400, "INVALID_MODEL_CONFIG")
		return
	}
	admissionStarted := time.Now()
	call, err := h.admit(r.Context(), role, payload.Model, session, requestID, validate)
	w.Header().Set("X-Roami-Model-Admission-Ms", strconv.FormatInt(time.Since(admissionStarted).Milliseconds(), 10))
	if err != nil {
		if r.Context().Err() != nil {
			return
		}
		switch err.Error() {
		case "MODEL_PROXY_DAILY_LIMIT":
			httpapi.Reject(w, 402, err.Error())
		case "MODEL_PROXY_USAGE_PENDING", "MODEL_PROXY_USAGE_UNKNOWN":
			httpapi.Reject(w, 409, err.Error())
		case "MODEL_GATEWAY_ROUTE_CHANGED":
			httpapi.Reject(w, 409, err.Error())
		case "MODEL_NOT_CONFIGURED", "MODEL_GATEWAY_CONFIGURATION_INVALID", "INVALID_MODEL_CONFIG", "MODEL_GATEWAY_UNAVAILABLE":
			httpapi.Reject(w, 503, err.Error())
		default:
			httpapi.Reject(w, 503, "MODEL_GATEWAY_STORAGE_FAILED")
		}
		return
	}
	w.Header().Set("X-Roami-Model-Call", call.ID)
	status, code, notSent := 0, "MODEL_GATEWAY_INTERRUPTED", false
	var usage *accounting.Usage
	defer func() {
		defer h.releaseAdmission()
		if err := h.state.accounting.Settle(call, usage, status, code, notSent); err != nil {
			log.Printf("model gateway: settlement failed call=%s", call.ID)
		}
	}()
	out, err := http.NewRequestWithContext(r.Context(), "POST", route.Endpoint+"/chat/completions", bytes.NewReader(body))
	if err != nil {
		notSent = true
		httpapi.Reject(w, 400, "INVALID_MODEL_CONFIG")
		return
	}
	for key, values := range r.Header {
		if strings.HasPrefix(strings.ToLower(key), "x-roami-") || key == "Cookie" || key == "Connection" || key == "Proxy-Authorization" || key == "Authorization" || strings.EqualFold(key, "X-Api-Key") || strings.EqualFold(key, "Api-Key") {
			continue
		}
		out.Header[key] = append([]string(nil), values...)
	}
	if route.Key != "" {
		out.Header.Set("Authorization", "Bearer "+route.Key)
	}
	response, err := h.Client.Do(out)
	if err != nil {
		var op *net.OpError
		notSent = errors.As(err, &op) && op.Op == "dial"
		code = "MODEL_TRANSPORT_FAILED"
		httpapi.Reject(w, 502, code)
		return
	}
	defer response.Body.Close()
	call.RecordUpstream(upstream.ResponseReceipt(response))
	status = response.StatusCode
	for _, key := range []string{"Content-Type", "Cache-Control", "Retry-After", "X-Request-Id", "Request-Id"} {
		if value := response.Header.Get(key); value != "" {
			w.Header().Set(key, value)
		}
	}
	w.WriteHeader(status)
	capture := protocol.NewCapture("openai-completions", strings.Contains(response.Header.Get("Content-Type"), "text/event-stream"))
	buffer := make([]byte, 32<<10)
	complete := false
	for {
		n, readErr := response.Body.Read(buffer)
		if n > 0 {
			capture.Feed(buffer[:n])
			if _, err = w.Write(buffer[:n]); err != nil {
				break
			}
			if capture.Streaming() {
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
		usage = capture.Finish(complete)
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
